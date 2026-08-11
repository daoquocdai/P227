# Portable VisionV2 runtime

`runtimev2` is a hardware-only port of the immutable implementation in the
sibling `P-227-thi/` directory. It imports the oracle preprocessing helpers and
reads the oracle YOLO/config/checkpoint assets directly. It neither imports
`src/vision` nor copies/mutates model weights.

There is no added Hz sampler. Like the oracle, the loop reads as fast as the
capture and inference allow, letterboxes every frame, and processes only odd
`frame_count` values. All temporal decisions use wall-clock `time.time()`.

Runtime selection:

1. `auto`: NVIDIA CUDA when available; otherwise Intel OpenVINO GPU; otherwise CPU.
2. `cuda`: require native PyTorch CUDA (InsightFace uses CUDA EP when enabled).
3. `intel`: require OpenVINO Intel GPU for YOLO and SDA-GCN; MediaPipe stays on CPU;
   InsightFace uses DirectML with CPU fallback.
4. `cpu`: portable CPU execution.

Install the matching dependency profile from the repository root:

```powershell
pip install -r requirements/vision-intel.txt
pip install -r requirements/vision-cuda.txt
pip install -r requirements/vision-cpu.txt
```

Intel preview:

```powershell
.venv\Scripts\python visionv2\runtimev2\realtime.py --video frontend\public\videos\kich_ban3.mp4 --device intel --identity
```

CUDA preview:

```powershell
python visionv2/runtimev2/realtime.py --video frontend/public/videos/kich_ban3.mp4 --device cuda --identity
```

Use `--camera 0` instead of `--video PATH` for a live camera. Press `q` to
close the preview. `--help` only parses arguments and never initializes models.

Run the permanent oracle-device-shim comparison from the repository root:

```powershell
.venv\Scripts\python tools\compare_vision_reference.py --frames 300 --output data\runtimev2-oracle-parity.json
```

The CPU harness applies only the `x.get_device()` to `x.device` safety shim to
the oracle SDA-GCN. It records the oracle observation times and replays them for
the candidate; it does not inject the production sampler or tracker behavior.
See `ORACLE_AUDIT.md` for the exhaustive behavior/difference inventory.
