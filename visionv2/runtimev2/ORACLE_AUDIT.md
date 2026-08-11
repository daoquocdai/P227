# Oracle-to-runtimev2 behavior audit

Source of truth: `visionv2/P-227-thi/realtime.py` and its directly imported
helpers/config. Values below are read from those files, not from `src/vision`.

| Behavior/parameter | Oracle | runtimev2 | Match |
| --- | --- | --- | --- |
| Default acquisition | `VideoCapture(0, CAP_DSHOW)` | Same for default/`--camera 0`; `--video` is CLI-only | Yes |
| Video FPS handling | None; read as fast as capture/inference permits | None | Yes |
| Frame skipping | Increment after letterbox; `frame_count % 2 == 0` immediately `continue` | Same | Yes |
| Hz scheduler/drop policy | None | None | Yes |
| Input geometry | Aspect resize to max side 1024, black pad to 1024×1024 | Same | Yes |
| YOLO call | `track(frame, persist=True, classes=0, verbose=False)` | Same | Yes |
| YOLO confidence/IoU | Not supplied; Ultralytics defaults | Not supplied | Yes |
| Person choice | Largest detected box by area | Same | Yes |
| Bounding-box padding | 30 px, clipped to 1024×1024 | Same | Yes |
| Minimum crop | Width and height at least 20 px | Same | Yes |
| Track ID | Ultralytics ID; no temporal reset on ID change | Same | Yes |
| MediaPipe | Pose detection confidence 0.5, tracking confidence 0.5 | Same | Yes |
| Keypoint extraction | Oracle `extractkpt.extractkpt.extract_from_crop` | Imports same oracle helper | Yes |
| Coordinate cleaning | Clip x/y to [0,1], oracle helper | Same helper | Yes |
| Skeleton normalization | Oracle dynamic normalization | Same helper | Yes |
| Temporal timestamps | `time.time()` after each sampled observation | Same | Yes |
| Inference window | When oldest buffered timestamp is at least 2.0 s old | Same | Yes |
| Window resample | Linear interpolation to 64 frames | Same | Yes |
| Root transform | Subtract joint 0 | Same | Yes |
| Pose normalization | Oracle `fusion.normalize_pose` | Same helper | Yes |
| Missing interpolation | Oracle `fusion.interpolate_missing` | Same helper | Yes |
| Kalman filter | Oracle `fusion.kalman_filter.apply_kalman_filter` | Same helper | Yes |
| SDA-GCN input | `(1,3,64,25,1)`, joint modality | Same | Yes |
| SDA-GCN classes | 5 classes; fall is index 1 | Same | Yes |
| Config | `joint/config.yaml`: adaptive true, dropout 0.5, 25 points, 1 person, 3 channels | Reads same file | Yes |
| Checkpoint | `joint/runs-best_val.pt`, `strict=False` | Reads same file and load policy | Yes |
| Window overlap | After inference remove observations older than 1.0 s | Same | Yes |
| Movement threshold | Mean joint displacement greater than 0.1 | Same | Yes |
| Pending movement phase | Update baseline before 2 s; cancellation check from 2 s to under 3 s | Same | Yes |
| Confirmation | Apply pending prediction after at least 3.0 s | Same | Yes |
| No-person behavior | Append zero pose, cancel pending events, recover from `Nga!` | Same | Yes |
| Fall recovery | While confirmed, movement greater than 0.1 sets `Khong nga` and cancels pending | Same | Yes |
| Face model | InsightFace `buffalo_l`, detection size 640×640 | Same | Yes |
| Face matching | Cosine similarity; recognized only above 0.45 | Same | Yes |
| Face retry/cache | 5 attempts, at least 1.0 s apart, recognized/locked-unknown cache; trim 100 to 50 | Same | Yes |
| Preview | Same boxes, ID/name, action and buffer overlays; `q` exits | Same | Yes |

## Classified differences

| File/logic | Difference | Classification | Reason |
| --- | --- | --- | --- |
| `realtime.py` argument parsing | Adds video/camera/device/identity/help inputs and hidden validation frame limit | CLI_ONLY | Standalone source selection and testability |
| Asset paths | Resolve YOLO/config/checkpoint/helpers from sibling immutable oracle | PATH_ONLY | Avoid duplicated weights/code |
| PyTorch selection | CUDA, Intel bootstrap CPU, or CPU | HARDWARE_COMPATIBILITY | Portable execution |
| SDA-GCN EdgeConv | `x.get_device()` becomes `x.device` at runtime | HARDWARE_COMPATIBILITY | Prevent CPU device index -1 without changing math |
| Intel detector | Same Ultralytics `track` call over an OpenVINO export; default backend override is `intel:gpu` | HARDWARE_COMPATIBILITY | Intel GPU execution backend |
| Intel SDA-GCN | Same input/output control flow over FP32 OpenVINO | HARDWARE_COMPATIBILITY | Intel GPU execution backend |
| InsightFace providers | CUDA EP, DirectML EP, or CPU EP | HARDWARE_COMPATIBILITY | Provider portability |
| Runtime diagnostics/returned trace | Adds diagnostics after initialization and test observations | CLI_ONLY | Auditing; no decision input |

There are no intentional differences classified as algorithm, sampling,
tracking, temporal, threshold, preprocessing, or decision logic.
