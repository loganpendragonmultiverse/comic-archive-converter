from __future__ import annotations

import argparse
import json
import lzma
import sys
import zipfile
import zlib
from pathlib import Path

import py7zr

from . import __version__
from .core import convert, preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert CBZ/ZIP and CB7/7Z comic archives.")
    parser.add_argument(
        "--version", action="version", version=f"comic-archive-convert {__version__}"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--format", choices=("cbz", "cb7"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Report declared member estimates and conflicts without conversion or writes",
    )
    args = parser.parse_args(argv)
    try:
        report = (preflight if args.preflight else convert)(args.source, args.output, args.format)
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (
        OSError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
        py7zr.exceptions.ArchiveError,
        py7zr.exceptions.AbsolutePathError,
        lzma.LZMAError,
        zlib.error,
        py7zr.exceptions.PasswordRequired,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1 if args.preflight and not report["ready"] else 0
