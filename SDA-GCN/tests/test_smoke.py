"""CPU smoke test for checkpoint loading and one synthetic SDA-GCN prediction."""

import os
from pathlib import Path
import sys
import unittest
import importlib

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "PyTorch is not installed")
class VisionSmokeTest(unittest.TestCase):
    def test_sda_gcn_cpu_prediction(self):
        from runtime.hardware import HardwareCapabilities, resolve_backend
        from runtime.inference import ActionInference

        config_path = ROOT / "work_dir/fall_detection/fall/config.yaml"
        weights_path = ROOT / "work_dir/fall_detection/fall/runs-best_val.pt"
        if not weights_path.exists():
            self.skipTest("SDA-GCN checkpoint is not present")
        with config_path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        module_name, class_name = config["model"].rsplit(".", 1)
        model_class = getattr(importlib.import_module(module_name), class_name)
        runner = ActionInference(
            model_class(**config["model_args"]), weights_path,
            resolve_backend("cpu", HardwareCapabilities()), ROOT / "work_dir/runtime_cache/tests",
        )
        output = runner(np.zeros(runner.INPUT_SHAPE, dtype=np.float32))
        self.assertEqual(tuple(output.shape), (1, 5))
        self.assertTrue(torch.isfinite(output).all())


if __name__ == "__main__":
    unittest.main()
