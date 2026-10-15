import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import numpy as np
import pytest
from PIL import Image

from backend.agents.image.agent import ImageAgent
from backend.agents.image.inference import ImageInference
from backend.agents.image.quality import assess_quality
from backend.agents.image.ranking import rank, retrieval_scores
from backend.config.settings import Settings
from backend.contracts.agents import ImageAgentResult, ImageMetadata, ImageReference
from backend.contracts.response import ClarificationRequest, ClarificationResponse
from backend.orchestrator.clarification import apply_clarification


def test_supplied_class_map_correction_is_recorded():
    root = Path("data/image")
    supplied = json.loads((root / "class_indices.supplied.json").read_text())
    corrected = json.loads((root / "class_indices.json").read_text())
    audit = json.loads((root / "label_correction.json").read_text())
    assert set(corrected) == set(supplied)
    assert sorted(corrected.values()) == list(range(40))
    changes = {
        key: [supplied[key], corrected[key]] for key in supplied if supplied[key] != corrected[key]
    }
    assert changes == audit["changes"]
    assert set(changes) == {"Persea americana", "Phyllanthus acidus"}


def picture(color=None, size=(128, 128)):
    rng = np.random.default_rng(44)
    image = (
        Image.new("RGB", size, color)
        if color
        else Image.fromarray(rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8))
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    content = buffer.getvalue()
    return content, ImageReference(
        image_id=uuid4(),
        metadata=ImageMetadata(
            mime_type="image/png", width=size[0], height=size[1], size_bytes=len(content)
        ),
    )


def provider(content):
    model = SimpleNamespace(
        model_id="fixture",
        labels=["Plant A", "Plant B"],
        infer=AsyncMock(
            return_value=(np.array([0.99, 0.01], dtype=np.float32), np.ones(2048, dtype=np.float32))
        ),
    )
    vectors = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "label": "Plant A",
                    "similarity": 0.99,
                    "pixel_hash": "one",
                    "point_id": "reference",
                }
            ]
        )
    )
    pg = SimpleNamespace(single=AsyncMock(return_value={"content": content}))
    catalog = SimpleNamespace(
        catalog=AsyncMock(
            return_value=(
                uuid4(),
                [
                    SimpleNamespace(name="Plant A", plant_id=uuid4(), plant_name="Plant A"),
                    SimpleNamespace(name="Plant B", plant_id=uuid4(), plant_name="Plant B"),
                ],
            )
        )
    )
    return ImageInference(Settings(_env_file=None), model, vectors, pg, catalog)


@pytest.mark.parametrize(
    "color,size",
    [("white", (128, 128)), ("black", (128, 128)), ("green", (128, 128)), (None, (12, 12))],
)
async def test_bad_quality_stops_before_inference(color, size):
    content, reference = picture(color, size)
    inference = provider(content)
    result = await inference.infer(reference, uuid4())
    assert result.quality.usable is False and not result.candidates
    inference.model.infer.assert_not_awaited()
    inference.vectors.search.assert_not_awaited()


async def test_real_pixels_produce_scoped_unconfirmed_candidates_and_provenance():
    content, reference = picture()
    inference = provider(content)
    sid = uuid4()
    result = await inference.infer(reference, sid)
    assert result.candidates[0].label == "Plant A"
    assert result.candidates[0].confidence < 0.8
    assert result.needs_clarification and not result.calibrated and not result.placeholder
    assert result.plant_part is None and result.quality.is_plant is None
    assert result.evidence[0].modality == "image" and result.evidence[0].evidence_type == "unknown"
    assert inference.postgres.single.call_args.args[1:] == (sid, reference.image_id)
    assert result.reference_ids == ["reference"]


async def test_missing_image_never_reads_another_session():
    content, reference = picture()
    inference = provider(content)
    inference.postgres.single.return_value = None
    with pytest.raises(ValueError, match="session"):
        await inference.infer(reference, uuid4())
    inference.model.infer.assert_not_awaited()


async def test_vector_outage_is_explicit_cnn_fallback():
    content, reference = picture()
    inference = provider(content)
    inference.vectors.search.side_effect = httpx.ConnectError("private server details")
    result = await inference.infer(reference, uuid4())
    assert result.candidates and result.needs_clarification
    assert result.strategy == "cnn_fallback"
    assert result.candidates[0].match_method == "image_cnn_fallback"
    assert any("unavailable" in item for item in result.limitations)
    assert "private server" not in result.model_dump_json()


async def test_unfamiliar_image_is_not_mapped_to_best_available_plant():
    content, reference = picture()
    inference = provider(content)
    inference.vectors.search.return_value[0]["similarity"] = 0.1
    result = await inference.infer(reference, uuid4())
    assert not result.candidates and result.clarification_question


async def test_missing_graph_label_is_reported_not_fabricated():
    content, reference = picture()
    inference = provider(content)
    inference.catalog.catalog.return_value = (uuid4(), [])
    result = await inference.infer(reference, uuid4())
    assert not result.candidates
    assert not result.scores[0]["graph_mapped"]


def test_reference_duplicates_do_not_inflate_votes():
    hits = [
        {"label": "A", "similarity": 0.9, "pixel_hash": "x"},
        {"label": "B", "similarity": 0.9, "pixel_hash": "y"},
    ]
    assert np.allclose(retrieval_scores(["A", "B"], hits * 20), [0.5, 0.5])
    assert rank(np.array([0.9, 0.1]), ["A", "B"], hits, "fusion").argmax() == 0


def test_replacement_image_preserves_lineage_and_budgets(state):
    _, reference = picture()
    state.clarification = ClarificationRequest()
    old_run, old_budgets = state.correlation.run_id, state.budgets.model_copy(deep=True)
    reply = ClarificationResponse(
        clarification_id=state.clarification.clarification_id, image_id=reference.image_id
    )
    apply_clarification(state, reply, reference)
    assert state.image == reference and state.belief.image_pending
    assert state.correlation.run_id == old_run and state.budgets == old_budgets
    assert state.clarification is None and state.termination.status == "RUNNING"


def test_replacement_image_cannot_be_forged(state):
    state.clarification = ClarificationRequest()
    with pytest.raises(ValueError):
        apply_clarification(
            state,
            ClarificationResponse(
                clarification_id=state.clarification.clarification_id, image_id=uuid4()
            ),
        )


async def test_agent_preserves_cancellation_and_default_is_honest():
    assert ImageAgent().provider is None
    assert ImageAgentResult().placeholder
    content, reference = picture()
    inference = provider(content)
    inference.model.infer.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await inference.infer(reference, uuid4())


def test_noise_is_not_declared_a_plant_by_quality_checks():
    content, _ = picture()
    assert assess_quality(content).is_plant is None
