# Third-party notices

Sniptype is distributed under the MIT License; see [LICENSE](LICENSE).
The application depends on the following separately licensed projects:

| Component | Use | License/source |
| --- | --- | --- |
| `pynput` | Global keyboard input | [PyPI](https://pypi.org/project/pynput/) |
| `pystray` | System-tray integration | [PyPI](https://pypi.org/project/pystray/) |
| `Pillow` | Image and icon handling | [Pillow license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| `yfinance` | Optional market-data lookups | [PyPI](https://pypi.org/project/yfinance/) |

The exact versions used by a build are recorded in
`source/requirements*.txt`. Before publishing a packaged build, include the
license and notice files shipped by each resolved dependency and native
library. Voice runtime and model attribution now belongs to the separate Snipvoice project.

This file is an attribution index, not a replacement for the upstream license
texts. Review the upstream notices for the exact versions and artifacts in the
release being distributed.
