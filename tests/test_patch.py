# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError
from textwrap import dedent
from types import SimpleNamespace

import pytest

from conda_build.source import (
    _ensure_CRLF,
    _ensure_LF,
    _guess_patch_strip_level,
    apply_patch,
)


@pytest.mark.parametrize(
    "patches,results",
    [
        pytest.param(
            [
                Path("one.txt"),
                Path("some", "common", "prefix", "two.txt"),
                Path("some", "common", "prefix", "three.txt"),
            ],
            [(0, False), (0, False), (0, False), (0, False)],
            id="strip level 0",
        ),
        pytest.param(
            [
                Path("some", "one.txt"),
                Path("some", "common", "prefix", "two.txt"),
                Path("some", "common", "prefix", "three.txt"),
            ],
            [(0, False), (1, False), (0, True), (0, True)],
            id="strip level 1",
        ),
        pytest.param(
            [
                Path("some", "common", "one.txt"),
                Path("some", "common", "prefix", "two.txt"),
                Path("some", "common", "prefix", "three.txt"),
            ],
            [(0, False), (1, False), (2, False), (0, True)],
            id="strip level 2",
        ),
        pytest.param(
            [
                Path("some", "common", "prefix", "one.txt"),
                Path("some", "common", "prefix", "two.txt"),
                Path("some", "common", "prefix", "three.txt"),
            ],
            [(0, False), (1, False), (2, False), (3, False)],
            id="strip level 3",
        ),
    ],
)
def test_patch_strip_level(
    patches: Path, results: list[tuple[int, bool]], tmp_path: Path
):
    # generate dummy files
    for patch in patches:
        (tmp_path / patch).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / patch).touch()

    src_dir = tmp_path
    assert _guess_patch_strip_level(patches, src_dir) == results[0]
    src_dir = src_dir / "some"
    assert _guess_patch_strip_level(patches, src_dir) == results[1]
    src_dir = src_dir / "common"
    assert _guess_patch_strip_level(patches, src_dir) == results[2]
    src_dir = src_dir / "prefix"
    assert _guess_patch_strip_level(patches, src_dir) == results[3]


@pytest.fixture
def patch_paths(tmp_path):
    paths = SimpleNamespace(
        deletion=tmp_path / "file-deletion.txt",
        modification=tmp_path / "file-modification.txt",
        creation=tmp_path / "file-creation.txt",
        diff=tmp_path / "patch.diff",
    )

    paths.deletion.write_text("hello\n")
    paths.modification.write_text("hello\n")
    paths.diff.write_text(
        dedent(
            """
            diff file-deletion.txt file-deletion.txt
            --- file-deletion.txt	2016-06-07 21:55:59.549798700 +0100
            +++ file-deletion.txt	1970-01-01 01:00:00.000000000 +0100
            @@ -1 +0,0 @@
            -hello
            diff file-creation.txt file-creation.txt
            --- file-creation.txt	1970-01-01 01:00:00.000000000 +0100
            +++ file-creation.txt	2016-06-07 21:55:59.549798700 +0100
            @@ -0,0 +1 @@
            +hello
            diff file-modification.txt file-modification.txt
            --- file-modification.txt	2016-06-08 18:23:08.384136600 +0100
            +++ file-modification.txt	2016-06-08 18:23:37.565136200 +0100
            @@ -1 +1 @@
            -hello
            +43770
            """
        ).lstrip()
    )

    return paths


def test_patch_paths(tmp_path, patch_paths, testing_config):
    assert patch_paths.deletion.exists()
    assert not patch_paths.creation.exists()
    assert patch_paths.modification.exists()
    assert patch_paths.modification.read_text() == "hello\n"

    apply_patch(str(tmp_path), patch_paths.diff, testing_config)

    assert not patch_paths.deletion.exists()
    assert patch_paths.creation.exists()
    assert patch_paths.modification.exists()
    assert patch_paths.modification.read_text() == "43770\n"


def test_ensure_unix_line_endings_with_nonutf8_characters(tmp_path):
    win_path = tmp_path / "win_le"
    win_path.write_bytes(b"\xf1\r\n")  # tilde-n encoded in latin1

    unix_path = tmp_path / "unix_le"
    _ensure_LF(win_path, unix_path)
    unix_path.read_bytes() == b"\xf1\n"


def test_lf_source_lf_patch(tmp_path, patch_paths, testing_config):
    _ensure_LF(patch_paths.modification)
    _ensure_LF(patch_paths.deletion)
    _ensure_LF(patch_paths.diff)

    apply_patch(str(tmp_path), patch_paths.diff, testing_config)

    assert patch_paths.modification.read_text() == "43770\n"


def test_lf_source_crlf_patch(tmp_path, patch_paths, testing_config):
    _ensure_LF(patch_paths.modification)
    _ensure_LF(patch_paths.deletion)
    _ensure_CRLF(patch_paths.diff)

    with pytest.raises(CalledProcessError):
        apply_patch(str(tmp_path), patch_paths.diff, testing_config)


def test_crlf_source_lf_patch(tmp_path, patch_paths, testing_config):
    _ensure_CRLF(patch_paths.modification)
    _ensure_CRLF(patch_paths.deletion)
    _ensure_LF(patch_paths.diff)

    with pytest.raises(CalledProcessError):
        apply_patch(str(tmp_path), patch_paths.diff, testing_config)


def test_crlf_source_crlf_patch(tmp_path, patch_paths, testing_config):
    _ensure_CRLF(patch_paths.modification)
    _ensure_CRLF(patch_paths.deletion)
    _ensure_CRLF(patch_paths.diff)

    apply_patch(str(tmp_path), patch_paths.diff, testing_config)

    assert patch_paths.modification.read_bytes() == b"43770\r\n"
