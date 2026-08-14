import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class PackagingExcludeTests(unittest.TestCase):
    def test_windows_and_macos_scripts_exclude_the_dead_ml_stack(self):
        expected = (
            "torch",
            "torchvision",
            "torchaudio",
            "cv2",
            "transformers",
            "onnxruntime",
            "scipy",
        )
        windows = os.path.join(ROOT, "build_release.bat")
        macos = os.path.join(ROOT, "build_release_macos.sh")
        with open(windows, encoding="utf-8") as handle:
            win_text = handle.read()
        with open(macos, encoding="utf-8") as handle:
            mac_text = handle.read()
        for name in expected:
            self.assertIn(name, win_text, name)
            self.assertIn(name, mac_text, name)

    def test_macos_declares_microphone_usage(self):
        path = os.path.join(ROOT, "build_release_macos.sh")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("NSMicrophoneUsageDescription", text)

    def test_optional_native_voice_runtime_is_collected_when_installed(self):
        windows = os.path.join(ROOT, "build_release.bat")
        macos = os.path.join(ROOT, "build_release_macos.sh")
        with open(windows, encoding="utf-8") as handle:
            win_text = handle.read()
        with open(macos, encoding="utf-8") as handle:
            mac_text = handle.read()
        for text in (win_text, mac_text):
            self.assertIn("VOICE_COLLECT_ARGS", text)
            self.assertIn("--collect-all transcribe_cpp", text)
            self.assertIn("--collect-all transcribe_cpp_native", text)


if __name__ == "__main__":
    unittest.main()
