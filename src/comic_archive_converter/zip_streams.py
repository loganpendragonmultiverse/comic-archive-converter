"""Bounded verification of the complete compressed ZIP member span."""

from __future__ import annotations

import bz2
import importlib
import lzma
import struct
import zipfile
import zlib
from typing import Any

CHUNK = 65536
MAX_LZMA_DICTIONARY = 64 * 1024 * 1024


def verify_compressed_stream(archive: zipfile.ZipFile, item: zipfile.ZipInfo) -> None:
    """Check real expanded size/CRC without ZipExtFile's declared-size truncation.

    ZipFile.open first retains stdlib local-header/name/overlap/encryption guards.
    Only one bounded output chunk is held. ZIP LZMA's optional EOS flag is honored.
    """
    with archive.open(item):
        pass
    source = archive.fp
    if source is None or item.compress_size < 0 or item.file_size < 0:
        raise zipfile.BadZipFile("Invalid compressed member extent")
    source.seek(item.header_offset + 26)
    lengths = source.read(4)
    if len(lengths) != 4:
        raise zipfile.BadZipFile("Truncated local ZIP header")
    name_bytes, extra_bytes = struct.unpack("<HH", lengths)
    source.seek(item.header_offset + 30 + name_bytes + extra_bytes)
    remaining = item.compress_size
    decoder: Any = None
    is_deflate = item.compress_type == zipfile.ZIP_DEFLATED
    if is_deflate:
        decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    elif item.compress_type == zipfile.ZIP_BZIP2:
        decoder = bz2.BZ2Decompressor()
    elif item.compress_type == zipfile.ZIP_LZMA:
        if remaining < 9:
            raise zipfile.BadZipFile("Truncated ZIP LZMA properties")
        properties = source.read(9)
        remaining -= len(properties)
        if len(properties) != 9 or struct.unpack("<H", properties[2:4])[0] != 5:
            raise zipfile.BadZipFile("Invalid ZIP LZMA properties")
        value = properties[4]
        dictionary = int.from_bytes(properties[5:9], "little")
        if value >= 225 or dictionary > MAX_LZMA_DICTIONARY:
            raise zipfile.BadZipFile("Invalid or oversized ZIP LZMA dictionary")
        decoder = lzma.LZMADecompressor(
            format=lzma.FORMAT_RAW,
            filters=[
                {
                    "id": lzma.FILTER_LZMA1,
                    "dict_size": dictionary,
                    "lc": value % 9,
                    "lp": (value // 9) % 5,
                    "pb": value // 45,
                }
            ],
        )
    elif item.compress_type in {20, 93}:
        # Available only on Python versions whose stdlib already accepts Zstandard.
        decoder = importlib.import_module("compression.zstd").ZstdDecompressor()
    elif item.compress_type != zipfile.ZIP_STORED:
        raise NotImplementedError(f"Unsupported ZIP compression method {item.compress_type}")
    count = crc = 0
    while remaining:
        chunk = source.read(min(CHUNK, remaining))
        if not chunk:
            raise zipfile.BadZipFile("Truncated compressed member")
        remaining -= len(chunk)
        pending = chunk
        while True:
            if decoder is None:
                decoded = pending
            else:
                try:
                    decoded = decoder.decompress(pending, min(CHUNK, item.file_size - count + 1))
                except Exception as exc:
                    raise zipfile.BadZipFile(f"Invalid compressed member: {exc}") from exc
            count += len(decoded)
            if count > item.file_size:
                raise zipfile.BadZipFile("Actual expanded member exceeds declared size")
            crc = zlib.crc32(decoded, crc)
            if decoder is None:
                break
            pending = decoder.unconsumed_tail if is_deflate else b""
            if decoder.eof:
                if decoder.unused_data or pending or remaining:
                    raise zipfile.BadZipFile("Trailing compressed member data")
                break
            if not pending and (is_deflate or decoder.needs_input):
                break
    # ZIP LZMA permits streams without an EOS marker only when bit 1 is clear.
    if (
        decoder is not None
        and not decoder.eof
        and (item.compress_type != zipfile.ZIP_LZMA or item.flag_bits & 2)
    ):
        raise zipfile.BadZipFile("Incomplete compressed stream")
    if count != item.file_size:
        raise zipfile.BadZipFile("Actual expanded member size differs from declaration")
    if crc != item.CRC:
        raise zipfile.BadZipFile("Bad CRC-32 for complete member")
