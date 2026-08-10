# GuardianCam Vision runtime

Production enters this package through `src.runtime.LocalRuntime` and
the selected `VisionEngine`; files here are not standalone applications.

Engine selections:

- `mock`: lightweight test engine
- `legacy` or `legacy_v1`: frozen binary V1 bone model
- `legacy_v2`: five-class V2 joint model; only raw class `1` is a fall candidate

Required inference artifacts:

- `yolov8n.pt`
- `work_dir/fall_detection/ntu25-bone/config.yaml`
- `work_dir/fall_detection/ntu25-bone/runs-best_val.pt`
- `work_dir/fall_detection/joint/config.yaml`
- `work_dir/fall_detection/joint/runs-best_val.pt`

The unchanged standalone V1 oracle lives in `legacy/vision_v1/realtime.py` and
is exercised only by `tests/test_vision/golden_regression.py`. Face identity in
production is supplied by the database-backed `FaceGallery`; old standalone
register and recognize applications are not runtime dependencies.
The unchanged V2 oracle lives in `legacy/vision_v2/realtime.py`; production
does not import from the top-level `visionv2/` source-material directory.
