import sys
import importlib.util as _ilu
from pathlib import Path

# tools/ingestion/__main__.py → tools/ → hld_generator_v2/
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_PARENT = _PROJECT_DIR.parent

# Add both project root and its parent to sys.path
for _p in (_PROJECT_PARENT, _PROJECT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Register hld_generator_v2 as 'hld_generator' so that internal absolute imports
# like `from hld_generator.tools...` resolve correctly regardless of folder name.
_hld_init = _PROJECT_DIR / "__init__.py"
if _hld_init.exists() and "hld_generator" not in sys.modules:
    _spec = _ilu.spec_from_file_location(
        "hld_generator", str(_hld_init),
        submodule_search_locations=[str(_PROJECT_DIR)]
    )
    _mod = _ilu.module_from_spec(_spec)
    sys.modules["hld_generator"] = _mod
    _spec.loader.exec_module(_mod)

from hld_generator.tools.ingestion.cli import main

main()
