from pathlib import Path
import sys


def mount(app, code=None, *, host_services=None):
    root = Path(code or Path(__file__).resolve().parents[1])
    source = str(root / "app")
    if source not in sys.path:
        sys.path.insert(0, source)
    from lung_rt.plugin import mount as register
    services = dict(host_services or {})
    services.setdefault("plugin_root", str(root))
    return register(app, services)
