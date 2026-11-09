"""Resolve source checkouts without assuming the private engineering layout."""
import os
from pathlib import Path
import sys


def _choose(explicit, candidates, marker, label):
    choices = [Path(explicit).expanduser()] if explicit else candidates
    for candidate in choices:
        if (candidate / marker).is_file():
            return candidate.resolve()
    raise RuntimeError(f"Set {label} to the source checkout containing {marker}.")


def resolve_sources(plugin_root, environ=None):
    root = Path(plugin_root).resolve()
    values = os.environ if environ is None else environ
    host = _choose(values.get("LOCAL_SUITE_SOURCE"),
                   [root.parent / "local-suite", root.parent],
                   "app/radai_panel.py", "LOCAL_SUITE_SOURCE")
    contour = _choose(values.get("CONTOURLAB_SOURCE"),
                      [root.parent / "contourlab", host.parent / "contourlab",
                       root.parent / "CONTOURLAB", host.parent / "CONTOURLAB"],
                      "app/radai_lung.py", "CONTOURLAB_SOURCE")
    return host, contour


def install_source_paths(plugin_root):
    root = Path(plugin_root).resolve()
    host, contour = resolve_sources(root)
    sys.path[:0] = [str(root / "app"), str(host / "app"), str(host / "tools"),
                   str(host / "build"), str(contour / "app")]
    return host, contour
