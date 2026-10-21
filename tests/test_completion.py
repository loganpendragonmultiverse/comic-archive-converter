import io
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import py7zr
import pytest

from comic_archive_converter import core
from comic_archive_converter.cli import main


def make_zip(path, names=("pages/one.txt",)):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"" if name.endswith("/") else b"synthetic page")


@pytest.mark.parametrize(
    "name",
    [
        "C:/one",
        "one:stream",
        "CON.txt",
        "pages//one",
        "./one",
        "trailing.",
        "new\nline",
        "back\\slash",
        *[
            name
            for prefix in ("COM", "LPT")
            for digit in ("¹", "²", "³")
            for name in (f"{prefix}{digit}", f"pages/{prefix}{digit}.png")
        ],
    ],
)
def test_conversion_rejects_portability_findings_before_payload_or_workspace(
    tmp_path, monkeypatch, name
):
    source, output = tmp_path / "source.cbz", tmp_path / "out.cbz"
    make_zip(source, (name,))
    assert not core.preflight(source, output, "cbz")["ready"]

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "unsafe headers must be rejected before decoding or creating a workspace"
        )

    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)
    monkeypatch.setattr(core.tempfile, "TemporaryDirectory", forbidden)
    with pytest.raises(ValueError, match="unsafe path"):
        core.convert(source, output, "cbz")
    assert not output.exists()


def test_zip_link_and_nonregular_members_are_rejected(tmp_path):
    for kind in (stat.S_IFLNK, stat.S_IFIFO):
        source = tmp_path / f"{kind}.cbz"
        with zipfile.ZipFile(source, "w") as archive:
            info = zipfile.ZipInfo("entry")
            info.create_system = 3
            info.external_attr = (kind | 0o644) << 16
            archive.writestr(info, b"target")
        with pytest.raises(ValueError, match="non-regular"):
            core.convert(source, tmp_path / f"{kind}-out.cbz", "cbz")


@pytest.mark.parametrize("family", ["cbz", "cb7"])
@pytest.mark.parametrize("output_format", ["cbz", "cb7"])
def test_real_formats_preserve_files_bytes_and_empty_directories(tmp_path, family, output_format):
    source = tmp_path / "initial.cbz"
    make_zip(source, ("empty/", "pages/one.txt", "pages/two.txt"))
    if family == "cb7":
        seven = tmp_path / "source.cb7"
        core.convert(source, seven, "cb7")
        source = seven
    original = source.read_bytes()
    output = tmp_path / ("out." + output_format)
    receipt = core.convert(source, output, output_format)
    assert receipt["member_count"] == 2 and receipt["directory_count"] == 2
    assert receipt["directories"] == ["empty", "pages"]
    assert receipt["source_stability_verified"]
    assert source.read_bytes() == original
    if output_format == "cbz":
        with zipfile.ZipFile(output) as archive:
            assert "empty/" in archive.namelist()
            assert archive.read("pages/one.txt") == b"synthetic page"
    else:
        with py7zr.SevenZipFile(output) as archive:
            assert {x.filename for x in archive.list() if x.is_directory} == {"empty", "pages"}


@pytest.mark.parametrize("mutation", ["source", "destination"])
def test_concurrent_changes_never_publish_wrong_receipts_or_overwrite(
    tmp_path, monkeypatch, mutation
):
    source, output = tmp_path / "source.cbz", tmp_path / "out.cbz"
    make_zip(source)
    original = core._write

    def write(*args):
        original(*args)
        if mutation == "source":
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr("new.txt", b"changed source")
        else:
            output.write_bytes(b"raced destination")

    monkeypatch.setattr(core, "_write", write)
    if mutation == "source":
        with pytest.raises(ValueError, match="source changed"):
            core.convert(source, output, "cbz")
        assert not output.exists()
    else:
        with pytest.raises(FileExistsError):
            core.convert(source, output, "cbz")
        assert output.read_bytes() == b"raced destination"
    assert not list(tmp_path.glob(".comic-convert-*"))


@pytest.mark.parametrize("loop", [False, True])
def test_existing_dangling_and_looping_output_links_are_preserved(tmp_path, loop):
    source, output = tmp_path / "source.cbz", tmp_path / "out.cbz"
    make_zip(source)
    target = output if loop else tmp_path / "not-created"
    try:
        output.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")
    assert "output already exists" in core.preflight(source, output, "cbz")["output_conflicts"]
    with pytest.raises(ValueError, match="already exists"):
        core.convert(source, output, "cbz")
    assert output.is_symlink()
    if not loop:
        assert not target.exists()


def test_missing_parent_and_nonregular_source_are_actionable(tmp_path, capsys):
    source = tmp_path / "source.cbz"
    make_zip(source)
    output = tmp_path / "missing/out.cbz"
    assert main([str(source), "--format", "cbz", "--output", str(output)]) == 2
    assert "parent" in capsys.readouterr().err
    with pytest.raises(ValueError, match="regular"):
        core.convert(tmp_path, tmp_path / "out.cbz", "cbz")
    assert not output.parent.exists()


def test_hashing_is_streamed_and_member_copy_enforces_actual_bytes(tmp_path, monkeypatch):
    source = tmp_path / "source.cbz"
    make_zip(source)

    def forbidden(*args, **kwargs):
        raise AssertionError("whole-file reads are forbidden in conversion")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    receipt = core.convert(source, tmp_path / "out.cbz", "cbz")
    assert receipt["member_count"] == 1
    with pytest.raises(ValueError, match="exceeds"):
        core._copy_member(io.BytesIO(b"xx"), io.BytesIO(), 1, 1)
    with pytest.raises(ValueError, match="differs"):
        core._copy_member(io.BytesIO(b""), io.BytesIO(), 1, 1)


def test_real_seven_decoder_actual_expansion_budget(tmp_path, monkeypatch):
    page = tmp_path / "one.txt"
    page.write_bytes(b"x" * 100)
    source = tmp_path / "source.cb7"
    with py7zr.SevenZipFile(source, "w") as archive:
        archive.write(page, "one.txt")
    original = py7zr.SevenZipFile.list

    def misleading_header(self):
        return [
            SimpleNamespace(
                filename=x.filename,
                uncompressed=1,
                is_directory=x.is_directory,
                is_file=x.is_file,
                is_symlink=x.is_symlink,
            )
            for x in original(self)
        ]

    monkeypatch.setattr(py7zr.SevenZipFile, "list", misleading_header)
    monkeypatch.setattr(core, "MAX_UNCOMPRESSED", 2)
    output = tmp_path / "out.cbz"
    with pytest.raises(py7zr.exceptions.DecompressionBombError):
        core.convert(source, output, "cbz")
    assert not output.exists() and not list(tmp_path.glob(".comic-convert-*"))


def test_unsupported_zip_metadata_is_a_cli_error(tmp_path, capsys):
    source = tmp_path / "unsupported.cbz"
    with zipfile.ZipFile(source, "w") as archive:
        info = zipfile.ZipInfo("page.txt")
        info.extract_version = 99
        info.create_version = 99
        archive.writestr(info, b"page")
    output = tmp_path / "out.cbz"
    assert main([str(source), "--format", "cbz", "--output", str(output)]) == 2
    assert capsys.readouterr().err and not output.exists()


def test_directory_payload_and_decoded_tree_mismatch_are_refused(tmp_path, monkeypatch):
    source = tmp_path / "source.cbz"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("bad/", b"not directory data")
        archive.writestr("page.txt", b"page")
    assert not core.preflight(source, tmp_path / "out.cbz", "cbz")["ready"]
    make_zip(source)
    original = core._extract_zip

    def incomplete(src, dst):
        original(src, dst)
        (dst / "pages/one.txt").write_bytes(b"changed size")

    monkeypatch.setattr(core, "_extract_zip", incomplete)
    with pytest.raises(ValueError, match="declared member"):
        core.convert(source, tmp_path / "out.cbz", "cbz")


def test_nulls_and_canonical_unicode_collisions_are_refused():
    for names in (["null\x00name"], ["é.txt", "é.txt"]):
        with pytest.raises(ValueError, match="unsafe|duplicate"):
            core._safe_names(names)


def test_preflight_receipt_is_json_serializable(tmp_path):
    source = tmp_path / "source.cbz"
    make_zip(source)
    report = core.preflight(source, tmp_path / "out.cbz", "cbz")
    assert json.loads(json.dumps(report))["ready"]


def test_version_matches_receipts(capsys):
    from comic_archive_converter import __version__

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"comic-archive-convert {__version__}"


def test_inconsistent_zip_directory_metadata_is_rejected(tmp_path):
    source = tmp_path / "source.cbz"
    with zipfile.ZipFile(source, "w") as archive:
        info = zipfile.ZipInfo("not-a-directory")
        info.create_system = 3
        info.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(info, b"page")
    assert not core.preflight(source, tmp_path / "out.cbz", "cbz")["ready"]
