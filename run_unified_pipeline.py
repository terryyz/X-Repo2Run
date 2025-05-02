#!/usr/bin/env python3
# Copyright (c) 2023-2024 Repo2Run Contributors

"""
Runner script for the Unified Pipeline.

This script provides a simple way to run the unified pipeline from the command line.

Usage:
    python run_unified_pipeline.py --repo-list repos.txt --output-dir output_path [options]
    python run_unified_pipeline.py --local-list dirs.txt --output-dir output_path [options]

See repo2run.unified_pipeline for full documentation.
"""

import sys
from repo2run.unified_pipeline import main

if __name__ == "__main__":
    sys.exit(main()) 