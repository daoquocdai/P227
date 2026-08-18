# SDA-GCN subsystem

This directory is the single authoritative SDA-GCN implementation used by P-227.
It owns the graph/model architecture, NTU-25 preprocessing, production config,
checkpoint, and the stable `SdaGcnRuntime` inference interface.

P-227 imports the subsystem only through `src/vision/sda_gcn.py`. YOLO remains in
`src/vision/yolov8n.pt` because it is the upstream person detector, not SDA-GCN.

## Runtime contract

Input is a skeleton tensor shaped `(N, 3, 64, 25, 1)`. `predict()` returns logits,
probabilities, and the predicted class. The production model has five classes and
class `1` is interpreted as fall evidence by P-227. Confirmation, cooldown, event,
database, and snapshot behavior remain outside this subsystem.

## Updating the model

1. Train with the model, graph, and preprocessing in this directory.
2. Export a checkpoint compatible with `config/production.yaml`.
3. Replace `weights/fall-detection-joint.pt` (and update the config only when the
   public tensor/class contract is unchanged).
4. Run `pytest tests/test_vision` and the application smoke tests.
5. Restart P-227. No application pipeline/service edit is required.
