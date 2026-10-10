from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.database.neo4j.medicinal import MedicinalPlantRepository
from backend.database.neo4j.models import Bioactivity, Document, Phytochemicals
from backend.database.neo4j.queries import TEMPLATES, MedicinalQuery


async def test_repository_only_uses_fixed_parameterized_templates():
    reader = AsyncMock()
    reader.read.return_value = [{"node": {"plant_name": "fixture"}}]
    repo = MedicinalPlantRepository(reader)
    text = "' MATCH (n) DELETE n //"
    result = await repo.plant_details(text, limit=3)
    assert result[0].plant_name == "fixture"
    query, parameters = reader.read.call_args.args
    assert query == TEMPLATES[MedicinalQuery.PLANT]
    assert text not in query
    assert parameters == {"plant_name": text, "limit": 3}
    assert reader.read.call_args.kwargs["timeout_seconds"] == 5


@pytest.mark.parametrize("limit", [0, 101, -1, True, 1.5])
async def test_repository_bounds(limit):
    reader = AsyncMock()
    with pytest.raises(ValueError):
        await MedicinalPlantRepository(reader).list_plants(limit=limit)
    reader.read.assert_not_awaited()


def test_schema_types_do_not_invent_constraints():
    assert Phytochemicals(inchi_key="fixture").classyfire_class is None
    assert Document(source_id=3, document_year="2001").source_id == 3
    assert Bioactivity(standard_value=2.5).standard_value == 2.5
    with pytest.raises(ValidationError):
        Document(source_id="3")
    with pytest.raises(ValidationError):
        Bioactivity(standard_value="2.5")


async def test_exact_plant_lookup_preserves_multiple_matches():
    reader = AsyncMock()
    reader.read.return_value = [{"node": {"plant_name": "same"}}, {"node": {"plant_name": "same"}}]
    assert len(await MedicinalPlantRepository(reader).plant_details("same")) == 2
