# hld_generator/__init__.py
# Namespace package shim.
# Registers hld_generator.shared.*, hld_generator.external.*, and
# hld_generator.agents.* as aliases for the real packages at project root.

import sys
from pathlib import Path
import importlib

_root = Path(__file__).parent.parent  # hld_generator_v2/

# Ensure project root is on sys.path
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

def _alias(hld_name: str, real_name: str):
    """Register hld_generator.X as an alias for X in sys.modules."""
    if hld_name not in sys.modules:
        try:
            real_mod = importlib.import_module(real_name)
            sys.modules[hld_name] = real_mod
        except ImportError:
            pass

# Register top-level aliases
_alias("hld_generator.shared", "shared")
_alias("hld_generator.external", "external")
_alias("hld_generator.agents", "agents")

# Register all submodules that are commonly used
import pkgutil

for _pkg, _prefix in [
    ("shared", "hld_generator.shared"),
    ("external", "hld_generator.external"),
    ("agents", "hld_generator.agents"),
]:
    try:
        _real = importlib.import_module(_pkg)
        for _importer, _modname, _ispkg in pkgutil.walk_packages(
            path=_real.__path__,
            prefix=_pkg + ".",
            onerror=lambda x: None
        ):
            _hld_mod_name = _modname.replace(_pkg + ".", _prefix + ".", 1)
            _alias(_hld_mod_name, _modname)
    except Exception:
        pass
