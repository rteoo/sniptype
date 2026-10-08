# Windows release preparation

```powershell
.\prepare-release-windows.ps1 -Tag v1.2.0 -DryRun
.\prepare-release-windows.ps1 -Tag v1.2.0
```

The helper requires clean `main` at `origin/main`, runs unittest and Ruff, then
invokes the existing staged `build_release.bat` and `build_installer.bat` and
hashes the installer. It does not publish or enable the separate macOS/MSIX
signing paths. Keep unrelated working files out of the checkout before running.
