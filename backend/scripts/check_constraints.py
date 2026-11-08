"""Fail if the installed packages are not exactly what constraints.txt pins.

Run after `pip install -r requirements.txt -c constraints.txt`, in CI and on a deploy
host. It catches two things that make builds quietly non-reproducible:

  * an installed package that has NO pin (a new dependency, or a platform-specific one
    like uvloop that a refresh run on another OS could not see), and
  * a pin that no longer matches what is installed.

    cd backend && python scripts/check_constraints.py

If it reports an unpinned package, run scripts/refresh_constraints.py (add platform-only
packages to constraints-extras.txt) and commit the result.
"""
import os
import sys
from importlib.metadata import distributions

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Installers and the tools that ship with a virtualenv; not part of the application.
IGNORED = {"pip", "setuptools", "wheel"}


def load_pins(path: str) -> dict:
    pins = {}
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue  # a pin for another platform
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==":
            print(f"constraints.txt line is not an exact pin: {line}")
            sys.exit(1)
        pins[canonicalize_name(requirement.name)] = specifiers[0].version
    return pins


def main() -> int:
    pins = load_pins(os.path.join(BACKEND, "constraints.txt"))
    installed = {canonicalize_name(d.metadata["Name"]): d.version for d in distributions()}

    unpinned = sorted(name for name in installed if name not in pins and name not in IGNORED)
    mismatched = sorted(
        (name, installed[name], version) for name, version in pins.items()
        if name in installed and installed[name] != version
    )

    for name in unpinned:
        print(f"NOT PINNED: {name}=={installed[name]} is installed but has no pin in constraints.txt")
    for name, have, want in mismatched:
        print(f"MISMATCH:   {name} is {have} but constraints.txt pins {want}")
    if unpinned or mismatched:
        print("\nRun scripts/refresh_constraints.py (platform-only packages go in constraints-extras.txt).")
        return 1
    print(f"OK: all {len(installed) - len(IGNORED & set(installed))} installed packages match their pins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
