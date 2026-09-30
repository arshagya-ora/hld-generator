# hld_generator/external/__init__.py
# Shim: re-export everything from the real `external` package at project root.

from pathlib import Path
import sys

_root = Path(__file__).parent.parent.parent  # hld_generator_v2/
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import importlib

_real = importlib.import_module("external")

def __getattr__(name):
    return getattr(_real, name)
