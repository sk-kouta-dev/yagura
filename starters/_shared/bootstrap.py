"""Monorepo-mode sys.path bootstrap.

When a starter is run from inside the yagura monorepo (e.g. during local
development), the ecosystem packages (`yagura_tools`, `yagura_state`,
`yagura_logger`, `yagura_auth`) are NOT pip-installed — they sit under
`packages/`.  We detect that situation and prepend every package directory
onto `sys.path` so `from yagura_tools.common import tools` resolves.

If the packages are already importable (user ran `pip install -r
requirements.txt`), this is a no-op.

Import this module at the top of every starter `tools.py` / `config.py`
*before* any `from yagura_tools.*` import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _packages_dir_from_here() -> Path | None:
    """Walk up the filesystem looking for a sibling `packages/` directory."""
    here = Path(__file__).resolve()
    for ancestor in (here.parent, *here.parents):
        candidate = ancestor.parent / "packages"
        if candidate.is_dir() and (candidate / "tools-common").is_dir():
            return candidate
    return None


def ensure_monorepo_packages_on_path() -> None:
    """Prepend every monorepo package directory onto `sys.path` if needed."""
    if importlib.util.find_spec("yagura_tools") is not None:
        # Packages are already importable (pip-installed or previously bootstrapped).
        return
    packages = _packages_dir_from_here()
    if packages is None:
        return
    for pkg in packages.iterdir():
        if pkg.is_dir() and pkg.name != "_shared":
            p = str(pkg)
            if p not in sys.path:
                sys.path.insert(0, p)


# Run on import so callers just do `import bootstrap  # noqa: F401`.
ensure_monorepo_packages_on_path()
