# hld_generator/shared/__init__.py
# Shim: re-export everything from the real `shared` package at project root.

from pathlib import Path
import sys

_root = Path(__file__).parent.parent.parent  # hld_generator_v2/
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Make `from hld_generator.shared.X import Y` work by
# forwarding attribute lookups to the real shared package.
import importlib, types

_real = importlib.import_module("shared")

def __getattr__(name):
    return getattr(_real, name)
