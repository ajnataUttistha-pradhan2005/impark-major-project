# Image Agent implementation and validation

The supplied Xception model and 2,507 JPEG leaf references were moved from the obsolete
`cnn-model-runner-main` sidecar into `data/image/`. The training recipe is preserved in
`training/image/train_model.py`; obsolete web server, client and deployment files were removed.
The model covers 40 classes. All 40 class names link uniquely to plant names in the current
PostgreSQL name projection. The original class-index JSON swapped Persea americana and
Phyllanthus acidus relative to the training folder order; `data/image/label_correction.json`
records the correction and both fingerprints. No weights were modified.

The runtime validates session ownership and image content, checks basic visual quality, then uses
one Xception pass for class scores and 2048-dimensional normalized features. Qdrant searches the
dedicated `plant_images_v1` cosine collection, filtered by model and dataset fingerprints. Fusion
uses 75% CNN scores and 25% deduplicated reference support for ranking. It returns up to five
graph-linked candidates, provenance, reference IDs, quality, limitations and separate image
evidence. User confirmation is required to establish the only active plant in a chat. An image
replacement resumes the existing LangGraph clarification checkpoint. A Qdrant query failure
reports `cnn_fallback`; a severely poor or low-similarity image requests a new leaf photo/name.
The final response model receives deterministic response context only.

The explicit index builder activated a manifest only after verifying all 2,507 corrected-scope
points. The superseded pre-correction generation was removed after the active count was checked.
The text collection was untouched. Web startup validates model and manifest IDs, vector size,
collection and point count; it does not seed or recreate Qdrant.

The reproducible `data/evaluation/image_comparison.json` comparison splits the supplied photos by
pixel hash: 2,017 references and 490 queries. Top-1 on these photos was CNN 490/490, retrieval
486/490 and fusion 490/490; all three were 490/490 Top-5. These are **not independent model
accuracy estimates**: the CNN may have trained on every supplied photo, and near-duplicate or
same-specimen leakage was not excluded. The model has no non-plant or other-part training/evaluation
set. Scores are uncalibrated, `is_plant` and `plant_part` remain unknown, and low similarity is only
a conservative rejection heuristic. Independent held-out photos and non-plant/part examples are
required before claiming reliable open-set classification.

Validation on the local configured services: three live API flows passed (image → candidate
confirmation → graph follow-up; unclear photo → replacement on same checkpoint; text/image
disagreement → contradiction and clarification). The repository suite passed 290 tests with 39
skipped opt-in integration cases. Ruff lint/format, mypy and pip dependency checks passed.
The local HTTP health endpoint reported `text-image-graph`, and capabilities reported
`image_classifier=true` with the 40-leaf-class scope and no part classifier.
See `backend/agents/image/README.md` for explicit setup and PowerShell commands.
> **Historical/design reference (updated 2026-10-18).** The active implementation is the DeepAgents main orchestrator with three specialist subagents, plus an outer LangGraph checkpoint/clarification adapter. This document may describe the removed deterministic harness, prior response policies, old test counts, or planned features. For current behavior use [implemented architecture](docs/architecture/README.md), [API and frontend](docs/api-and-frontend/README.md), [file map](docs/repository-map/README.md), and the source code. Do not treat historical statements below as current runtime guarantees.
