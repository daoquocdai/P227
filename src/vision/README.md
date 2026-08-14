# GuardianCam Vision runtime

Production enters this package through `src.runtime.LocalRuntime` and the
single `RuntimeV2VisionPipeline` in `pipeline.py`. `mock` remains test-only.

`visionv2/` at repository root is the standalone oracle. Production never
imports it; `tools/compare_vision_reference.py` is the explicit comparison
boundary. Enabled cameras use ordered per-camera workers while immutable model
state is shared. The production pipeline is a local, integration-safe
adaptation of that immutable runtime; it does not import either standalone
reference tree at runtime.

The canonical pipeline preserves verified VisionV2 behavior: YOLO person
tracking, MediaPipe pose, the runtimev2 wall-clock two-second window resampled
to 64 joint frames, five-class SDA-GCN inference, and class `1` as the fall
candidate. It runs synchronously in the sole camera capture loop, before the
raw frame is published for streaming; no production sampler, worker queue, or
frame-dropping layer sits in front of Vision.

Required inference artifacts:

- `yolov8n.pt`
- `work_dir/fall_detection/joint/config.yaml`
- `work_dir/fall_detection/joint/runs-best_val.pt`

On supported Intel Windows systems, `VISION_DEVICE=auto` exports fingerprinted
OpenVINO artifacts into `VISION_MODEL_CACHE_DIR`, validates SDA-GCN FP32 parity,
and runs YOLO/SDA-GCN on Intel GPU. CUDA-capable hosts keep native PyTorch/YOLO
CUDA ahead of the Intel path. CPU fallback is explicit in startup logs.
Face identity is supplied by the database-backed `FaceGallery`.
