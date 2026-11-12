#!/usr/bin/env python3
"""Command line entry point. See `python trader.py --help`."""

import sys

from signals.cli import main

if __name__ == "__main__":
    sys.exit(main())
