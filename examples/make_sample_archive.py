"""Create an owned, valid PNG/ComicInfo/empty-directory preservation fixture."""

import argparse
import struct
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def png(red: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(b"\x00" + bytes((red, y * 2, 100)) * 64 for y in range(96))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 96, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("output already exists")
    with ZipFile(args.output, "x", compression=ZIP_DEFLATED) as archive:
        archive.writestr("pages/001.png", png(40))
        archive.writestr("pages/002.png", png(180))
        archive.writestr(
            "ComicInfo.xml", "<ComicInfo><Title>Synthetic Converter Fixture</Title></ComicInfo>"
        )
        archive.writestr("empty/", b"")


if __name__ == "__main__":
    main()
