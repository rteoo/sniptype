"""On-demand voice-model cache: download, verify, install, delete.

Models never live in the snippet data directory or the installer. The cache
is a non-roaming per-user location, overridable for tests and power users.

A download is streamed to a sibling temp file, hashed as it arrives, and
promoted with ``os.replace`` only after size and SHA-256 match the catalog.
Corrupt or cancelled downloads leave the last valid install in place.
"""

import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request

from voice_catalog import catalog_entry, catalog_entry_by_id


ENV_VOICE_CACHE = "TXT_XPANDER_VOICE_CACHE"
CACHE_DIR_NAME = "voice-models"
MANIFEST_NAME = "manifest.json"
PARTIAL_SUFFIX = ".partial"
MAX_REDIRECTS = 5
CHUNK_SIZE = 1024 * 1024
# ceiling: single-file GGUF downloads only. A catalog entry that points at an
# archive needs a path-safe extractor before it can be added.


class VoiceModelError(Exception):
    """User-visible failure while installing or removing a model."""


def default_voice_cache_dir(system=None):
    """Non-roaming cache for regenerable model files.

    Windows: ``%LOCALAPPDATA%\\Txt Xpander\\voice-models``
    macOS: ``~/Library/Caches/Txt Xpander/voice-models``
    Linux: ``~/.cache/txt-xpander/voice-models``
    """
    override = os.environ.get(ENV_VOICE_CACHE)
    if override:
        return os.path.abspath(os.path.expanduser(override))

    from platform_support import current_os

    os_name = system or current_os()
    home = os.path.expanduser("~")
    if os_name == "windows":
        root = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(root, "Txt Xpander", CACHE_DIR_NAME)
    if os_name == "darwin":
        return os.path.join(home, "Library", "Caches", "Txt Xpander", CACHE_DIR_NAME)
    return os.path.join(home, ".cache", "txt-xpander", CACHE_DIR_NAME)


def model_dir(cache_dir, entry):
    return os.path.join(cache_dir, _safe_entry_id(entry["id"]))


def model_path(cache_dir, entry):
    return os.path.join(model_dir(cache_dir, entry), entry["filename"])


def manifest_path(cache_dir, entry):
    return os.path.join(model_dir(cache_dir, entry), MANIFEST_NAME)


def _read_manifest(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def model_is_installed(entry, cache_dir):
    """True when the pinned file exists and the recorded digest matches."""
    path = model_path(cache_dir, entry)
    manifest = _read_manifest(manifest_path(cache_dir, entry))
    if manifest is None or not os.path.isfile(path):
        return False
    if manifest.get("sha256") != entry["sha256"]:
        return False
    if manifest.get("size_bytes") != entry["size_bytes"]:
        return False
    try:
        return os.path.getsize(path) == entry["size_bytes"]
    except OSError:
        return False


def installed_model_path(entry, cache_dir):
    if model_is_installed(entry, cache_dir):
        return model_path(cache_dir, entry)
    return None


def _ensure_parent(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _free_bytes(path):
    probe = path
    while probe and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    if not probe:
        probe = os.path.abspath(os.sep)
    return shutil.disk_usage(probe).free


def _safe_entry_id(model_id):
    if not isinstance(model_id, str) or not model_id:
        raise VoiceModelError("Identificador de modelo inválido.")
    if model_id in (".", "..") or "/" in model_id or "\\" in model_id or os.path.sep in model_id:
        raise VoiceModelError("Identificador de modelo inválido.")
    return model_id


def _safe_url(url):
    if not isinstance(url, str):
        raise VoiceModelError("URL do modelo inválida.")
    if not url.lower().startswith("https://"):
        raise VoiceModelError("O download do modelo só aceita HTTPS.")
    return url


class _LimitedRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise VoiceModelError("Redirecionamento inseguro recusado.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_LimitedRedirect)


def download_model(entry, cache_dir, progress=None, cancel_event=None, opener=None):
    """Download and verify ``entry`` into ``cache_dir``.

    ``progress`` is ``callable(bytes_done, bytes_total)``. ``cancel_event`` is
    a ``threading.Event``. ``opener`` is a test hook matching
    ``urllib.request.OpenerDirector.open``. Returns the installed model path.
    """
    if model_is_installed(entry, cache_dir):
        return model_path(cache_dir, entry)

    dest_dir = model_dir(cache_dir, entry)
    dest_file = model_path(cache_dir, entry)
    os.makedirs(dest_dir, exist_ok=True)

    needed = int(entry["size_bytes"] * 1.1) + CHUNK_SIZE
    free = _free_bytes(dest_dir)
    if free < needed:
        raise VoiceModelError(
            "Espaço em disco insuficiente para baixar o modelo de voz."
        )

    url = _safe_url(entry["url"])
    fd, tmp_path = tempfile.mkstemp(
        prefix=entry["id"] + ".",
        suffix=PARTIAL_SUFFIX,
        dir=dest_dir,
    )
    os.close(fd)
    hasher = hashlib.sha256()
    written = 0
    try:
        request = urllib.request.Request(url, method="GET")
        open_url = opener or _opener().open
        with open_url(request, timeout=30) as response, \
                open(tmp_path, "wb") as handle:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise VoiceModelError("Download do modelo cancelado.")
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                hasher.update(chunk)
                written += len(chunk)
                if progress is not None:
                    progress(written, entry["size_bytes"])
                if written > entry["size_bytes"]:
                    raise VoiceModelError(
                        "O arquivo baixado é maior que o tamanho pinado."
                    )
        digest = hasher.hexdigest()
        if written != entry["size_bytes"]:
            raise VoiceModelError(
                "Tamanho do modelo baixado não confere com o catálogo."
            )
        if digest != entry["sha256"]:
            raise VoiceModelError(
                "A verificação SHA-256 do modelo de voz falhou."
            )
        os.replace(tmp_path, dest_file)
        tmp_path = None
        _write_manifest(entry, cache_dir, digest)
        return dest_file
    except VoiceModelError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise VoiceModelError(f"Falha ao baixar o modelo de voz: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _write_manifest(entry, cache_dir, digest):
    payload = {
        "id": entry["id"],
        "profile": entry["profile"],
        "filename": entry["filename"],
        "sha256": digest,
        "size_bytes": entry["size_bytes"],
        "license_id": entry["license_id"],
        "upstream_model": entry["upstream_model"],
    }
    path = manifest_path(cache_dir, entry)
    _ensure_parent(path)
    fd, tmp = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def delete_model(entry, cache_dir):
    """Remove only the catalog-owned directory for ``entry``."""
    target = os.path.abspath(model_dir(cache_dir, entry))
    cache_root = os.path.abspath(cache_dir)
    try:
        inside = os.path.commonpath([target, cache_root]) == cache_root
    except ValueError:
        inside = False
    if not inside:
        raise VoiceModelError("Recusa em apagar fora do cache de modelos.")
    if os.path.basename(target) != entry["id"]:
        raise VoiceModelError("Recusa em apagar um diretório que não é do catálogo.")
    if not os.path.exists(target):
        return True
    shutil.rmtree(target)
    return True


def delete_profile_model(profile, cache_dir):
    entry = catalog_entry(profile)
    if entry is None:
        raise VoiceModelError("Perfil de voz desconhecido.")
    return delete_model(entry, cache_dir)


def resolve_entry(profile_or_id):
    entry = catalog_entry(profile_or_id)
    if entry is None:
        entry = catalog_entry_by_id(profile_or_id)
    if entry is None:
        raise VoiceModelError("Perfil de voz desconhecido.")
    return entry
