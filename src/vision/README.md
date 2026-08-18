# Canonical production Vision

Production enters this package through `src.runtime.LocalRuntime` and
`CanonicalVisionPipeline` in `pipeline.py`. SDA-GCN is accessed only through
`src/vision/sda_gcn.py`; model internals live in the top-level `SDA-GCN/` tree.

## Runtime contract

```text
CameraRuntime capture
  ├── raw FrameHub → realtime MJPEG/preview
  └── even source frame → LatestFrameSlot(capacity=1)
                         → per-camera Vision worker
                         → CanonicalVisionPipeline
```

Vision therefore does not run synchronously inside the capture loop. Slow
inference overwrites one pending packet instead of creating a queue, while raw
streaming continues at source cadence.

Temporal semantics use `FramePacket.source_timestamp`:

- video: media/source timeline;
- live camera: monotonic capture time;
- `source_epoch`/sticky discontinuity prevents windows crossing loops/reconnects.

## Model semantics

The canonical pipeline preserves:

- YOLO person tracking/crop behavior;
- MediaPipe Pose extraction;
- existing preprocessing and 64-frame resampling;
- five-class SDA-GCN output;
- class `1` as fall candidate;
- existing confirmation/recovery/movement rules;
- known-face cosine threshold `>0.45`;
- five qualifying Unknown observations at one-second source-time intervals.

Required artifacts:

- `yolov8n.pt`;
- `../../SDA-GCN/config/production.yaml`;
- `../../SDA-GCN/weights/fall-detection-joint.pt`.

## Hardware

`VISION_DEVICE=auto` selects CUDA first, then Intel OpenVINO GPU, then CPU.
MediaPipe Pose runs on CPU. Identity uses configured ONNX Runtime providers;
DirectML is supported on Windows with CPU fallback. The one-shot privacy face
detector intentionally uses CPU provider for native stability.

Known identities come from the database-backed `FaceGallery`. InsightFace
`buffalo_l` is required only when Identity is enabled.

## Product boundaries

- Fall is always enabled whenever Vision is enabled.
- Identity OFF disables continuous recognition/Unknown events but not Fall.
- Product thresholds are applied by `VisionProductPolicy`, not model math.
- Snapshot privacy is handled at the manager commit boundary using the exact
  event packet.
- Viewer count and presentation flags never create inference.
