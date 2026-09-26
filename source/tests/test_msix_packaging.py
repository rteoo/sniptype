import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
TMP = Path(__file__).resolve().parent / "tmp"
TMP.mkdir(exist_ok=True)
FOUNDATION = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"
DESKTOP = "{http://schemas.microsoft.com/appx/manifest/desktop/windows10}"

spec = importlib.util.spec_from_file_location("build_msix", ROOT / "packaging" / "build_msix.py")
build_msix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_msix)


def render():
    return build_msix.render_manifest("1.0.0.0")


class MsixManifestTests(unittest.TestCase):
    def test_version_follows_source_with_store_reserved_zero(self):
        self.assertRegex(build_msix.source_version(), r"^\d+\.\d+\.\d+\.0$")

    def test_identity_matches_the_partner_center_reservation(self):
        root = ET.fromstring(render())
        identity = root.find(f"{FOUNDATION}Identity")
        self.assertEqual(identity.get("Name"), "Strateo.SnipType")
        self.assertEqual(identity.get("Publisher"), "CN=95CECFD0-1222-4FC9-8C10-A17DEFD99C08")
        self.assertEqual(identity.get("Version"), "1.0.0.0")
        self.assertEqual(root.find(f"{FOUNDATION}Properties/{FOUNDATION}PublisherDisplayName").text,
                         "Strateo")

    def test_display_name_matches_the_store_reservation(self):
        # Partner Center rejects a package whose DisplayName differs from the reserved name.
        root = ET.fromstring(render())
        self.assertEqual(root.find(f"{FOUNDATION}Properties/{FOUNDATION}DisplayName").text, "SnipType")
        names = {element.get("DisplayName") for element in root.iter() if element.get("DisplayName")}
        self.assertEqual(names, {"SnipType"})

    def test_manifest_declares_both_interface_languages_portuguese_first(self):
        # The first resource is the package's default language; each declared
        # language needs its own Store listing in Partner Center.
        root = ET.fromstring(render())
        languages = [r.get("Language") for r in root.iter(f"{FOUNDATION}Resource")]
        self.assertEqual(languages, ["pt-BR", "en-US"])

    def test_manifest_declares_full_trust_and_opt_in_startup_task_only(self):
        root = ET.fromstring(render())
        self.assertEqual(list(root.iter(f"{FOUNDATION}DeviceCapability")), [])
        task = next(root.iter(f"{DESKTOP}StartupTask"))
        self.assertEqual(task.get("Enabled"), "false")
        application = next(root.iter(f"{FOUNDATION}Application"))
        self.assertEqual(application.get("Executable"), "Sniptype.exe")


class MsixLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.dist = os.path.join(self.temp.name, "dist")
        self.layout = os.path.join(self.temp.name, "layout")
        os.makedirs(self.dist)

    def test_layout_requires_the_built_executable(self):
        with self.assertRaises(FileNotFoundError):
            build_msix.stage_layout(self.dist, self.layout, render())

    def test_layout_refuses_a_user_library_beside_the_exe(self):
        Path(self.dist, "Sniptype.exe").write_bytes(b"")
        Path(self.dist, "snippets.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_msix.stage_layout(self.dist, self.layout, render())
        self.assertFalse(os.path.exists(self.layout))

    def test_layout_holds_app_manifest_and_store_assets(self):
        Path(self.dist, "Sniptype.exe").write_bytes(b"")
        build_msix.stage_layout(self.dist, self.layout, render())

        self.assertTrue(os.path.isfile(os.path.join(self.layout, "Sniptype.exe")))
        self.assertTrue(os.path.isfile(os.path.join(self.layout, "AppxManifest.xml")))
        for filename, size in build_msix.ASSETS.items():
            with Image.open(os.path.join(self.layout, "Assets", filename)) as image:
                self.assertEqual(image.size, size)
        with self.assertRaises(FileExistsError):
            build_msix.stage_layout(self.dist, self.layout, render())


if __name__ == "__main__":
    unittest.main()
