from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import py7zr

from .core import convert


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert CBZ/ZIP and CB7/7Z comic archives.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--format", choices=("cbz", "cb7"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = convert(args.source, args.output, args.format)
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError, zipfile.BadZipFile, py7zr.Bad7zFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
