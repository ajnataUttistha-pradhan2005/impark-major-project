# Image Agent handoff

Input is a session-registered image reference with validated metadata. The development upload
service validates MIME/bytes/decoding/dimensions off the event loop, then discards pixels.
TODO: implement a blob repository/upload lifecycle before real model inference.

Required future pipeline: validation -> quality -> plant/non-plant gate -> pretrained/custom CNN
inference -> candidate ranking/calibration -> plant part -> observation. Qdrant vector retrieval is
an optional internal stage once R-008/R-009 are resolved. Keep inference off the asyncio loop.

`ImageInferenceProvider` and `VectorRepository` are ports only. The default agent returns empty
candidates, unchecked quality and `placeholder=True`. Never substitute invented classifications.
