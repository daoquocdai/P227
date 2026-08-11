"""Hardware-only portable port of the untouched VisionV2 oracle."""

from .hardware import RuntimeSelection, select_runtime

__all__ = ["RuntimeSelection", "select_runtime"]
