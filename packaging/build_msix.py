"""Pack the Windows PyInstaller build into an MSIX for Microsoft Store submission.

Run after ``build_release.bat`` has produced ``dist\\Sniptype``. The package
identity is the public Partner Center reservation (Product identity page); the
Store re-signs the upload, so no code-signing certificate is involved.
``makeappx.exe`` ships with the Windows SDK.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape, quoteattr

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOURCE_ENTRY = os.path.join(ROOT, "source", "sniptype.pyw")
ICON_SOURCE = os.path.join(ROOT, "source", "sniptype-app-icon.png")
EXECUTABLE = "Sniptype.exe"
STARTUP_TASK_ID = "SniptypeStartup"
DISPLAY_NAME = "SnipType"
DESCRIPTION = "Expansor de texto na bandeja do Windows."

IDENTITY_NAME = "Strateo.SnipType"
PUBLISHER = "CN=95CECFD0-1222-4FC9-8C10-A17DEFD99C08"
PUBLISHER_DISPLAY_NAME = "Strateo"

# Store-required tile and logo assets, at their 100% scale sizes.
ASSETS = {
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
}

MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap desktop rescap">
  <Identity Name={name} Publisher={publisher} Version={version} ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>{display_name}</DisplayName>
    <PublisherDisplayName>{publisher_display_name}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="pt-BR" />
  </Resources>
  <Applications>
    <Application Id="Sniptype" Executable="{executable}" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName={display_name_attr}
        Description={description}
        BackgroundColor="transparent"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png" />
      <Extensions>
        <desktop:Extension Category="windows.startupTask" Executable="{executable}" EntryPoint="Windows.FullTrustApplication">
          <desktop:StartupTask TaskId="{startup_task_id}" Enabled="false" DisplayName={display_name_attr} />
        </desktop:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""


def source_version():
    with open(SOURCE_ENTRY, encoding="utf-8") as handle:
        match = re.search(r"^Version: (\d+)\.(\d+)\.(\d+)$", handle.read(), re.M)
    if not match:
        raise ValueError("Version not found in the source/sniptype.pyw docstring")
    # The Store reserves the fourth field; submissions must leave it at 0.
    return ".".join(match.groups()) + ".0"


def render_manifest(version):
    return MANIFEST_TEMPLATE.format(
        name=quoteattr(IDENTITY_NAME),
        publisher=quoteattr(PUBLISHER),
        version=quoteattr(version),
        display_name=escape(DISPLAY_NAME),
        display_name_attr=quoteattr(DISPLAY_NAME),
        publisher_display_name=escape(PUBLISHER_DISPLAY_NAME),
        description=quoteattr(DESCRIPTION),
        executable=EXECUTABLE,
        startup_task_id=STARTUP_TASK_ID,
    )


def write_assets(assets_dir):
    os.makedirs(assets_dir, exist_ok=True)
    with Image.open(ICON_SOURCE) as icon:
        icon = icon.convert("RGBA")
        for filename, size in ASSETS.items():
            icon.resize(size, Image.LANCZOS).save(os.path.join(assets_dir, filename))


def stage_layout(dist_dir, layout_dir, manifest):
    if not os.path.isfile(os.path.join(dist_dir, EXECUTABLE)):
        raise FileNotFoundError(f"{EXECUTABLE} not found in {dist_dir}; run build_release.bat first")
    # Older builds kept the user's live library beside the exe. Shipping one
    # would publish personal snippets to every Store install.
    if os.path.exists(os.path.join(dist_dir, "snippets.json")):
        raise ValueError(f"{dist_dir} holds a user snippets.json; rebuild with build_release.bat")
    if os.path.exists(layout_dir):
        raise FileExistsError(f"Layout directory already exists: {layout_dir}")
    shutil.copytree(dist_dir, layout_dir)
    write_assets(os.path.join(layout_dir, "Assets"))
    with open(os.path.join(layout_dir, "AppxManifest.xml"), "w", encoding="utf-8") as handle:
        handle.write(manifest)


def find_makeappx():
    explicit = os.environ.get("SNIPTYPE_MAKEAPPX")
    if explicit:
        return explicit
    on_path = shutil.which("makeappx.exe")
    if on_path:
        return on_path
    kits = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                        "Windows Kits", "10", "bin")
    candidates = sorted(glob.glob(os.path.join(kits, "10.*", "x64", "makeappx.exe")))
    if not candidates:
        raise FileNotFoundError("makeappx.exe not found; install the Windows SDK or set SNIPTYPE_MAKEAPPX")
    return candidates[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist-dir", default=os.path.join(ROOT, "dist", "Sniptype"))
    parser.add_argument("--work-dir", default=os.path.join(ROOT, "build", "msix"))
    parser.add_argument("--output-dir", default=os.path.join(ROOT, "dist", "msix"))
    args = parser.parse_args(argv)

    version = source_version()
    layout_dir = os.path.join(args.work_dir, "layout")
    stage_layout(args.dist_dir, layout_dir, render_manifest(version))

    os.makedirs(args.output_dir, exist_ok=True)
    package = os.path.join(args.output_dir, f"Sniptype-{version}-x64.msix")
    subprocess.run([find_makeappx(), "pack", "/d", layout_dir, "/p", package, "/o"], check=True)
    print(package)
    return 0


if __name__ == "__main__":
    sys.exit(main())
