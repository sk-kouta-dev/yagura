"""Shared utilities for yagura-tools-* packages.

This is an internal helper, not a public package. Tool packages copy
their `lazy_import` helper from here or vendor it.
"""

from __future__ import annotations

import importlib
from typing import Any


def lazy_import(module_name: str, package_hint: str | None = None) -> Any:
    """Import a module on demand, raising a friendly error if missing."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        hint = package_hint or module_name
        raise ImportError(
            f"This tool requires '{hint}'. "
            f"Install the package that provides it (e.g. `pip install {hint}`)."
        ) from exc
