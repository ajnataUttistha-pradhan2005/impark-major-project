# Image Agent

The Image Agent accepts a session-registered JPEG/PNG/WebP reference. Upload validation caps
content at 5 MiB and 16 million pixels; PostgreSQL stores the bytes for the chat. At inference,
quality checks reject severely tiny, flat, blurred or exposed images. One CPU Xception forward pass
returns 40 leaf-class scores and a 2048-dimensional normalized feature vector. Qdrant searches a
dedicated cosine collection, scoped by model and dataset fingerprints. Deterministic fusion ranks
the CNN and reference-image scores; exact catalog names link labels to graph plant IDs. The agent
returns typed candidates and separate image evidence. The harness requires user confirmation before
establishing the single active plant. A low-similarity image asks for a clearer leaf/name, and a
Qdrant outage falls back to CNN suggestions. No raw model score is calibrated certainty.

The source artifacts are in `data/image/`: `xception_model.keras` and `dataset/` are ignored by Git;
`class_indices.json`, `label_correction.json` and `index_manifest.json` are tracked. The original
runner's class map swapped Persea americana and Phyllanthus acidus. The corrected map changes labels
only; weights and features are unchanged. `training/image/train_model.py` preserves the training
recipe. The obsolete runner web service and deployment files were removed.

PowerShell from repository root, after local stores, migrations and text catalog setup:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[image]'
.\.venv\Scripts\python.exe -m backend.agents.image.admin extract --dataset 'data/image/dataset' --model 'data/image/xception_model.keras' --classes 'data/image/class_indices.json' --output 'data/image/features.npz'
.\.venv\Scripts\python.exe -m backend.agents.image.build_index --cache 'data/image/features.npz' --manifest 'data/image/index_manifest.json'
.\.venv\Scripts\python.exe -m backend.agents.image.evaluate --cache 'data/image/features.npz' --output 'data/evaluation/image_comparison.json'
$env:IMAGE_RUN_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest tests/api/test_image_live.py -q
```

Set `IMAGE_ENABLED=true`, `IMAGE_MODEL_PATH=data/image/xception_model.keras`,
`IMAGE_CLASSES_PATH=data/image/class_indices.json`,
`IMAGE_MANIFEST_PATH=data/image/index_manifest.json` and local/cloud `QDRANT_URL` in `.env`.
The same configuration keys work for cloud stores. Index provisioning and activation are explicit,
never performed on web startup. Startup validates the model, manifest, collection shape and exact
scoped point count. The 40-class dataset covers leaf photos only; plant/non-plant and plant-part
classification are unavailable. The comparison report uses supplied training-derived photos, so
its split scores cannot establish independent accuracy, calibration or out-of-distribution rejection.
Closely related specimen leakage has not been ruled out.
