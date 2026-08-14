import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_models import (
    ENV_VOICE_CACHE,
    VoiceModelError,
    default_voice_cache_dir,
    download_model,
)


class VoiceCachePathTests(unittest.TestCase):
    def test_env_override_wins(self):
        previous = os.environ.get(ENV_VOICE_CACHE)
        os.environ[ENV_VOICE_CACHE] = os.path.join(tempfile.gettempdir(), "voice-cache-x")
        try:
            self.assertTrue(default_voice_cache_dir().endswith("voice-cache-x"))
        finally:
            if previous is None:
                os.environ.pop(ENV_VOICE_CACHE, None)
            else:
                os.environ[ENV_VOICE_CACHE] = previous

    def test_windows_uses_localappdata_not_roaming(self):
        path = default_voice_cache_dir(system="windows")
        self.assertIn("Txt Xpander", path)
        self.assertIn("voice-models", path)
        self.assertNotIn("Roaming", path)

    def test_macos_and_linux_are_cache_dirs(self):
        mac = default_voice_cache_dir(system="darwin")
        linux = default_voice_cache_dir(system="linux")
        self.assertIn("Library", mac)
        self.assertIn("Caches", mac)
        self.assertIn(".cache", linux)


class VoiceDownloadPolicyTests(unittest.TestCase):
    def test_file_and_http_urls_are_rejected(self):
        for url in ("file:///tmp/evil.gguf", "http://example.com/model.gguf"):
            entry = {
                "id": "fixture-model",
                "filename": "fixture.gguf",
                "url": url,
                "sha256": "0" * 64,
                "size_bytes": 1,
                "license_id": "MIT",
                "upstream_model": "fixture",
            }
            with self.assertRaises(VoiceModelError):
                download_model(entry, tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
