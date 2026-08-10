# GuardianCam Vision V1 runtime

Production enters this package through `src.runtime.LocalRuntime` and
`LegacyVisionEngine`; files here are not standalone applications.

Required inference artifacts:

- `yolov8n.pt`
- `work_dir/fall_detection/ntu25-bone/config.yaml`
- `work_dir/fall_detection/ntu25-bone/runs-best_val.pt`

The unchanged standalone V1 oracle lives in `legacy/vision_v1/realtime.py` and
is exercised only by `tests/test_vision/golden_regression.py`. Face identity in
production is supplied by the database-backed `FaceGallery`; old standalone
register and recognize applications are not runtime dependencies.
