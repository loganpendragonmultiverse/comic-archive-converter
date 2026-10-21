import struct
import zipfile
import zlib

import pytest

from comic_archive_converter.core import convert, preflight

CODECS = [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA]


def forged_prefix(path, codec, name="page.txt", payload=b"AB", declared=b"A"):
    with zipfile.ZipFile(path, "w", compression=codec) as z:
        z.writestr(name, payload)
    with zipfile.ZipFile(path) as z:
        central = z.start_dir
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, 14, zlib.crc32(declared))
    struct.pack_into("<I", data, 22, len(declared))
    struct.pack_into("<I", data, central + 16, zlib.crc32(declared))
    struct.pack_into("<I", data, central + 24, len(declared))
    path.write_bytes(data)


@pytest.mark.parametrize("codec", CODECS, ids=["stored", "deflate", "bzip2", "lzma"])
def test_complete_stream_rejects_prefix_forgery(tmp_path, codec):
    source = tmp_path / "forged.cbz"
    output = tmp_path / "out.cbz"
    forged_prefix(source, codec)
    before = source.read_bytes()
    assert preflight(source, output, "cbz")["ready"]
    with pytest.raises(zipfile.BadZipFile, match="expanded|size|CRC"):
        convert(source, output, "cbz")
    assert not output.exists() and source.read_bytes() == before


@pytest.mark.parametrize("codec", CODECS, ids=["stored", "deflate", "bzip2", "lzma"])
def test_all_original_codecs_preserve_real_complete_bytes(tmp_path, codec):
    source = tmp_path / "source.cbz"
    output = tmp_path / "out.cbz"
    payload = bytes(range(256)) * 1200
    with zipfile.ZipFile(source, "w", compression=codec) as z:
        z.writestr("page.bin", payload)
        z.writestr("empty/", b"")
    receipt = convert(source, output, "cbz")
    assert receipt["total_bytes"] == len(payload)
    with zipfile.ZipFile(output) as z:
        assert z.read("page.bin") == payload


@pytest.mark.parametrize("codec", CODECS, ids=["stored", "deflate", "bzip2", "lzma"])
def test_directory_stream_also_validated(tmp_path, codec):
    source = tmp_path / "forged.cbz"
    output = tmp_path / "out.cbz"
    forged_prefix(source, codec, "empty/", declared=b"")
    with zipfile.ZipFile(source, "a") as z:
        z.writestr("page.txt", b"ok")
    assert preflight(source, output, "cbz")["ready"]
    with pytest.raises(zipfile.BadZipFile):
        convert(source, output, "cbz")
    assert not output.exists()


def mutate_compressed_span(path, transform):
    with zipfile.ZipFile(path) as archive:
        item = archive.infolist()[0]
        central = archive.start_dir
    data = bytearray(path.read_bytes())
    start = item.header_offset + 30 + len(item.filename.encode()) + len(item.extra)
    end = start + item.compress_size
    changed = transform(bytes(data[start:end]))
    data = data[:start] + changed + data[end:]
    newcentral = central + len(changed) - item.compress_size
    struct.pack_into("<I", data, 18, len(changed))
    struct.pack_into("<I", data, newcentral + 20, len(changed))
    struct.pack_into("<I", data, len(data) - 22 + 16, newcentral)
    path.write_bytes(data)


@pytest.mark.parametrize("codec", CODECS[1:], ids=["deflate", "bzip2", "lzma"])
@pytest.mark.parametrize("mutation", ["unfinished", "trailing"])
def test_complete_codec_end_and_no_trailing_stream_data(tmp_path, codec, mutation):
    source = tmp_path / "source.cbz"
    with zipfile.ZipFile(source, "w", compression=codec) as z:
        z.writestr("page.bin", b"ABC" * 3000)
    mutate_compressed_span(
        source, lambda data: data[:-1] if mutation == "unfinished" else data + b"extra"
    )
    with pytest.raises((zipfile.BadZipFile, OSError, EOFError)):
        convert(source, tmp_path / "out.cbz", "cbz")
    assert not (tmp_path / "out.cbz").exists()


def test_lzma_dictionary_allocation_is_bounded(tmp_path):
    source = tmp_path / "source.cbz"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_LZMA) as z:
        z.writestr("page.bin", b"ABC")
    mutate_compressed_span(
        source, lambda data: data[:5] + (128 * 1024 * 1024).to_bytes(4, "little") + data[9:]
    )
    with pytest.raises(zipfile.BadZipFile, match="dictionary"):
        convert(source, tmp_path / "out.cbz", "cbz")


def test_complete_crc_mismatch_is_rejected(tmp_path):
    source = tmp_path / "source.cbz"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("page.bin", b"ABC")
    with zipfile.ZipFile(source) as z:
        central = z.start_dir
    data = bytearray(source.read_bytes())
    struct.pack_into("<I", data, 14, 0)
    struct.pack_into("<I", data, central + 16, 0)
    source.write_bytes(data)
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        convert(source, tmp_path / "out.cbz", "cbz")
