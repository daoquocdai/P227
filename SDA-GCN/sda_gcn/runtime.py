from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "production.yaml"
DEFAULT_CHECKPOINT_PATH = PACKAGE_ROOT / "weights" / "fall-detection-joint.pt"


class SdaGcnRuntime:
    """Stable SDA-GCN inference boundary used by the P-227 vision pipeline."""

    EXPECTED_MODEL = {"num_class": 5, "num_person": 1, "num_point": 25, "in_channels": 3}
    EXPECTED_BONE_MODALITY = False
    OUTPUT_CLASSES = 5

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        checkpoint_path: str | Path = DEFAULT_CHECKPOINT_PATH,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        self.checkpoint_path = Path(checkpoint_path).expanduser().resolve()
        self.model: Any = None

    def load_config(self, yaml_module: Any) -> dict[str, Any]:
        with self.config_path.open("r", encoding="utf-8") as handle:
            config = yaml_module.safe_load(handle)
        model_args = dict(config.get("model_args") or {})
        actual = {name: model_args.get(name) for name in self.EXPECTED_MODEL}
        if actual != self.EXPECTED_MODEL:
            raise ValueError(f"Expected SDA-GCN config {self.EXPECTED_MODEL}, got {actual}")
        if config.get("test_feeder_args", {}).get("bone") is not self.EXPECTED_BONE_MODALITY:
            raise ValueError(f"SDA-GCN config bone modality must be {self.EXPECTED_BONE_MODALITY}")
        model_args["graph"] = "sda_gcn.graph.ntu_rgb_d_hierarchy.Graph"
        return model_args

    def load_pytorch_model(self, torch_module: Any, yaml_module: Any, device: Any) -> Any:
        from sda_gcn.model import Model

        model = Model(**self.load_config(yaml_module)).to(device)
        try:
            weights = torch_module.load(self.checkpoint_path, map_location=device, weights_only=True)
        except TypeError:
            weights = torch_module.load(self.checkpoint_path, map_location=device)
        if not isinstance(weights, dict):
            raise ValueError("SDA-GCN checkpoint must contain a state_dict mapping")
        weights = OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())
        model.load_state_dict(weights, strict=False)
        model.eval()
        self.model = model
        return model

    def bind_model(self, model: Any) -> None:
        """Bind an optimized model (for example an OpenVINO wrapper)."""
        self.model = model

    def predict(self, skeleton_tensor: Any, torch_module: Any) -> tuple[Any, Any, int]:
        if self.model is None:
            raise RuntimeError("SDA-GCN runtime has no bound model")
        with torch_module.inference_mode():
            logits = self.model(skeleton_tensor)
        expected = (1, self.OUTPUT_CLASSES)
        if tuple(logits.shape) != expected:
            raise RuntimeError(f"SDA-GCN must return shape {expected}, got {tuple(logits.shape)}")
        if not bool(torch_module.isfinite(logits).all().item()):
            raise RuntimeError("SDA-GCN returned non-finite logits")
        probabilities = torch_module.softmax(logits, dim=1).squeeze(0)
        predicted_class = int(torch_module.argmax(probabilities).item())
        return logits, probabilities, predicted_class
