import json
import stat
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import py7zr
import pytest

from comic_archive_converter import core
from comic_archive_converter.cli import main


def test_zip_estimates_conflicts_and_zero_writes(tmp_path, monkeypatch, capsys):
    source, output = tmp_path / "one.cbz", tmp_path / "new" / "out.cb7"
    with ZipFile(source, "w") as archive:
        archive.writestr("pages/", b"")
        archive.writestr("pages/one.jpg", b"abc")
    before = source.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not extract, read member data or write")

    monkeypatch.setattr(core, "_extract", forbidden)
    monkeypatch.setattr(core, "_write", forbidden)
    monkeypatch.setattr(core.tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(ZipFile, "open", forbidden)
    report = core.preflight(source, output, "cb7")
    assert report["ready"] and report["declared_expanded_bytes"] == 3
    assert report["member_count"] == 2
    assert "Declared estimates" in report["size_note"]
    assert not output.parent.exists() and source.read_bytes() == before
    assert main([str(source), "--format", "cb7", "--output", str(output), "--preflight"]) == 0
    assert json.loads(capsys.readouterr().out)["preflight"]
    report = core.preflight(source, source, "cb7")
    assert len(report["output_conflicts"]) == 3
    assert main([str(source), "--format", "cbz", "--output", str(source), "--preflight"]) == 1


def test_unsafe_duplicate_links_and_encryption(tmp_path):
    source = tmp_path / "unsafe.cbz"
    with ZipFile(source, "w") as archive:
        for name in ("../one.jpg", "C:/two.jpg", "/abs.jpg", "same.jpg", "SAME.jpg"):
            archive.writestr(name, b"a")
        link = ZipInfo("link.jpg")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "target")
    data = bytearray(source.read_bytes())
    for magic, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        index = data.find(magic)
        data[index + offset] |= 1
    source.write_bytes(data)
    report = core.preflight(source, tmp_path / "out.cb7", "cb7")
    problems = [problem for member in report["members"] for problem in member["issues"]]
    assert {
        "unsafe path",
        "duplicate path",
        "symbolic link or non-regular member",
        "encrypted member",
    } <= set(problems)
    assert not report["ready"]


def test_real_seven_and_header_metadata_gaps(tmp_path, monkeypatch):
    source = tmp_path / "one.cb7"
    page = tmp_path / "one.jpg"
    page.write_bytes(b"page")
    with py7zr.SevenZipFile(source, "w") as archive:
        archive.write(page, "one.jpg")
    assert core.preflight(source, tmp_path / "out.cbz", "cbz")["declared_expanded_bytes"] == 4

    class Headers:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def needs_password(self):
            return True

        def list(self):
            return [
                SimpleNamespace(
                    filename="link",
                    uncompressed=None,
                    is_directory=False,
                    is_symlink=True,
                    is_file=False,
                )
            ]

    monkeypatch.setattr(core.py7zr, "SevenZipFile", Headers)
    report = core.preflight(source, tmp_path / "out.cbz", "cbz")
    assert report["declared_expanded_bytes"] is None
    assert not report["declared_sizes_complete"]
    assert "declared size unavailable" in report["members"][0]["issues"]
    assert not report["ready"]


def test_limits_empty_temp_and_invalid_inputs(tmp_path, monkeypatch):
    source = tmp_path / "empty.zip"
    with ZipFile(source, "w"):
        pass
    output = tmp_path / "out.cbz"
    assert not core.preflight(source, output, "cbz")["ready"]
    with ZipFile(source, "w") as archive:
        archive.writestr("one.jpg", b"abc")
    monkeypatch.setattr(core, "MAX_ENTRIES", 0)
    monkeypatch.setattr(core, "MAX_UNCOMPRESSED", 1)
    (tmp_path / ".out.tmp.cbz").write_bytes(b"occupied")
    report = core.preflight(source, output, "cbz")
    assert len(report["issues"]) == 2
    assert report["output_conflicts"] == ["temporary output already exists"]
    with pytest.raises(ValueError):
        core.preflight(source, output, "rar")
    with pytest.raises(ValueError):
        core.preflight(tmp_path / "missing", output, "cbz")
    wrong = tmp_path / "wrong.tar"
    wrong.write_bytes(b"x")
    with pytest.raises(ValueError):
        core.preflight(wrong, output, "cbz")


def test_seven_encryption_never_creates_output(tmp_path, capsys):
    page = tmp_path / "page.jpg"
    page.write_bytes(b"synthetic page")
    source, output = tmp_path / "encrypted.cb7", tmp_path / "out.cbz"
    with py7zr.SevenZipFile(source, "w", password="fixture-only") as archive:
        archive.write(page, "page.jpg")
    report = core.preflight(source, output, "cbz")
    assert "encrypted member" in report["members"][0]["issues"]
    assert not report["ready"] and not output.exists()
    hidden = tmp_path / "hidden.cb7"
    with py7zr.SevenZipFile(
        hidden, "w", password="fixture-only", header_encryption=True
    ) as archive:
        archive.write(page, "page.jpg")
    assert main([str(hidden), "--format", "cbz", "--output", str(output), "--preflight"]) == 2
    assert capsys.readouterr().err and not output.exists()
