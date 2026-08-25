"""Import ``sniptype.pyw`` as a module on every OS.

``importlib.machinery.SOURCE_SUFFIXES`` contains ``.pyw`` only on Windows, so
the plain ``import sniptype`` the tests used to do raises
``ModuleNotFoundError`` on macOS and Linux before a single test runs. Loading
the file explicitly by path keeps the modules that exercise ``Sniptype``
running on the whole CI matrix without depending on the ``.pyw`` loader (the
``.pyw`` extension is what makes ``pythonw`` launch it without a console).

Usage::

    from app_module import sniptype as tx
"""

import importlib.util
import os
import sys
from importlib.machinery import SourceFileLoader


MODULE_NAME = "sniptype"
SOURCE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
MODULE_PATH = os.path.join(SOURCE_DIR, f"{MODULE_NAME}.pyw")


def _load():
    """Load (once) and return the app module, registered under its own name."""
    existing = sys.modules.get(MODULE_NAME)
    if existing is not None:
        return existing

    if SOURCE_DIR not in sys.path:
        sys.path.insert(0, SOURCE_DIR)

    loader = SourceFileLoader(MODULE_NAME, MODULE_PATH)
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so that anything importing ``sniptype`` during
    # execution resolves to the same object the tests patch.
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(MODULE_NAME, None)
        raise
    return module


sniptype = _load()
