#!/usr/bin/env python3
"""Backward-compatible char_001 entry point for the generic local pipeline."""

from generate_local_comfyui import main


if __name__ == "__main__":
    # main() defaults to char_001 when no sample directory is supplied.
    main()
