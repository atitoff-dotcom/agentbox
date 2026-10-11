#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Executable module entry point for agentbox: python -m agentbox
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
