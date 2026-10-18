#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Executable module entry point for agentbox: python -m agentbox
"""

import sys

# Force UTF-8 encoding on standard I/O streams across all platforms
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="surrogateescape")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

