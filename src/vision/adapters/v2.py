from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from src.models.frame import FramePacket
from src.models.vision import VisionResult
from src.vision.adapters.legacy import DEFAULT_INSIGHTFACE_ROOT, VISION_ROOT, LegacyVisionEngine
from src.vision.session import VisionSession

FALL_CLASS_ID = 1


class V2VisionEngine(LegacyVisionEngine):
    """Five-class joint-input V2 model behind the shared Local Hub contract."""

    EXPECTED_MODEL = {"num_class": 5, "num_person": 1, "num_point": 25, "in_channels": 3}
    EXPECTED_BONE_MODALITY = False
    OUTPUT_CLASSES = 5
    FALL_CLASS_ID = FALL_CLASS_ID

    def __init__(
        self,
        yolo_path: str | Path = VISION_ROOT / "yolov8n.pt",
        config_path: str | Path = VISION_ROOT / "work_dir" / "fall_detection" / "joint" / "config.yaml",
        checkpoint_path: str | Path = VISION_ROOT / "work_dir" / "fall_detection" / "joint" / "runs-best_val.pt",
        known_faces_dir: str | Path = VISION_ROOT / "register face",
        identity_enabled: bool = False,
        identity_provider: str = "auto",
        insightface_root: str | Path = DEFAULT_INSIGHTFACE_ROOT,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            yolo_path=yolo_path,
            config_path=config_path,
            checkpoint_path=checkpoint_path,
            known_faces_dir=known_faces_dir,
            identity_enabled=identity_enabled,
            identity_provider=identity_provider,
            insightface_root=insightface_root,
            **kwargs,
        )

    @staticmethod
    def _model_input(data_numpy: np.ndarray, deps: SimpleNamespace) -> np.ndarray:
        del deps
        return data_numpy

    def _result(self, packet: FramePacket, session: VisionSession, started: float, **kwargs: Any) -> VisionResult:
        result = super()._result(packet, session, started, **kwargs)
        result.metadata.update(
            {
                "engine": "legacy_v2",
                "model_version": "v2",
                "raw_class_id": result.metadata.get("raw_class"),
            }
        )
        return result
