"""P-227 integration adapter for the replaceable top-level SDA-GCN subsystem."""

import sys
from pathlib import Path

SDA_GCN_ROOT = Path(__file__).resolve().parents[2] / "SDA-GCN"
if str(SDA_GCN_ROOT) not in sys.path:
    sys.path.insert(0, str(SDA_GCN_ROOT))

from sda_gcn import DEFAULT_CHECKPOINT_PATH, DEFAULT_CONFIG_PATH, SdaGcnRuntime  # noqa: E402
from sda_gcn.preprocessing import (  # noqa: E402
    apply_kalman_filter,
    clean_out_of_bounds_data,
    extract_from_crop,
    interpolate_missing,
    normalize_pose,
    normalize_skeleton_dynamic,
)

__all__ = [
    "DEFAULT_CHECKPOINT_PATH",
    "DEFAULT_CONFIG_PATH",
    "SdaGcnRuntime",
    "apply_kalman_filter",
    "clean_out_of_bounds_data",
    "extract_from_crop",
    "interpolate_missing",
    "normalize_pose",
    "normalize_skeleton_dynamic",
]
