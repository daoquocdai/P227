import unittest

from runtime.hardware import BackendResolutionError, HardwareCapabilities, resolve_backend


class BackendResolverTests(unittest.TestCase):
    def test_nvidia_cuda_has_priority(self):
        caps = HardwareCapabilities(torch_cuda=True, torch_hip=False, torch_device_name="RTX")
        self.assertEqual(resolve_backend("auto", caps).backend, "torch_cuda")

    def test_amd_rocm(self):
        caps = HardwareCapabilities(torch_cuda=True, torch_hip=True, torch_device_name="Radeon")
        result = resolve_backend("auto", caps)
        self.assertEqual((result.backend, result.vendor), ("torch_rocm", "AMD"))

    def test_amd_windows_directml(self):
        caps = HardwareCapabilities(directml_usable=True, adapter_names=("AMD Radeon 780M",))
        self.assertEqual(resolve_backend("auto", caps).backend, "torch_directml")

    def test_intel_openvino(self):
        caps = HardwareCapabilities(openvino_gpu=True, openvino_gpu_name="Intel Iris Xe")
        self.assertEqual(resolve_backend("auto", caps).backend, "openvino")

    def test_cpu_fallback(self):
        self.assertEqual(resolve_backend("auto", HardwareCapabilities()).backend, "cpu")

    def test_forced_cuda_error(self):
        with self.assertRaisesRegex(BackendResolutionError, "NVIDIA CUDA is unavailable"):
            resolve_backend("cuda", HardwareCapabilities())

    def test_forced_intel_error(self):
        with self.assertRaisesRegex(BackendResolutionError, "OpenVINO GPU is unavailable"):
            resolve_backend("intel", HardwareCapabilities())


if __name__ == "__main__":
    unittest.main()
