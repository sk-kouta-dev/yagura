"""Add each ecosystem package to sys.path so smoke tests can import them."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGES_DIR = _PROJECT_ROOT / "packages"

for pkg_dir in _PACKAGES_DIR.iterdir():
    if not pkg_dir.is_dir():
        continue
    if str(pkg_dir) not in sys.path:
        sys.path.insert(0, str(pkg_dir))
