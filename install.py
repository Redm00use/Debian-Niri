#!/usr/bin/env python3
"""
Nixdots → Debian Migration Installer
Convenience wrapper - delegates to installer/install.py
"""
import sys
from pathlib import Path

installer = Path(__file__).resolve().parent / "installer" / "install.py"
if installer.exists():
    exec(installer.read_text())
else:
    print(f"ERROR: Installer not found at {installer}", file=sys.stderr)
    sys.exit(1)
