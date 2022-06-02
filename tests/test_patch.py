import os
from textwrap import dedent
from types import SimpleNamespace
from subprocess import CalledProcessError

import pytest

from conda_build.source import (_ensure_unix_line_endings, _ensure_win_line_endings,
                                _guess_patch_strip_level, apply_patch)


def test_patch_strip_level(testing_workdir, monkeypatch):
    patchfiles = {'some/common/prefix/one.txt',
                      'some/common/prefix/two.txt',
                      'some/common/prefix/three.txt'}
    folders = ('some', 'common', 'prefix')
    files = ('one.txt', 'two.txt', 'three.txt')
    os.makedirs(os.path.join(*folders))
    for file in files:
        with open(os.path.join(os.path.join(*folders), file), 'w') as f:
            f.write('hello\n')
    assert _guess_patch_strip_level(patchfiles, os.getcwd()) == (0, False)
    monkeypatch.chdir(folders[0])
    assert _guess_patch_strip_level(patchfiles, os.getcwd()) == (1, False)
    monkeypatch.chdir(folders[1])
    assert _guess_patch_strip_level(patchfiles, os.getcwd()) == (2, False)
    monkeypatch.chdir(folders[2])
    assert _guess_patch_strip_level(patchfiles, os.getcwd()) == (3, False)
    monkeypatch.chdir(testing_workdir)


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


# TODO :: These should require a build env with patch (or m2-patch) in it.
#         at present, only ci/github/install_conda_build_test_deps installs
#         this.
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
    _ensure_unix_line_endings(win_path, unix_path)
    unix_path.read_bytes() == b"\xf1\n"


def test_lf_source_lf_patch(tmp_path, patch_paths, testing_config):
    _ensure_unix_line_endings(patch_paths.modification)
    _ensure_unix_line_endings(patch_paths.deletion)
    _ensure_unix_line_endings(patch_paths.diff)

    apply_patch(str(tmp_path), patch_paths.diff, testing_config)

    assert patch_paths.modification.read_text() == "43770\n"


def test_lf_source_crlf_patch(tmp_path, patch_paths, testing_config):
    _ensure_unix_line_endings(patch_paths.modification)
    _ensure_unix_line_endings(patch_paths.deletion)
    _ensure_win_line_endings(patch_paths.diff)

    with pytest.raises(CalledProcessError):
        apply_patch(str(tmp_path), patch_paths.diff, testing_config)


def test_crlf_source_lf_patch(tmp_path, patch_paths, testing_config):
    _ensure_win_line_endings(patch_paths.modification)
    _ensure_win_line_endings(patch_paths.deletion)
    _ensure_unix_line_endings(patch_paths.diff)

    with pytest.raises(CalledProcessError):
        apply_patch(str(tmp_path), patch_paths.diff, testing_config)


def test_crlf_source_crlf_patch(tmp_path, patch_paths, testing_config):
    _ensure_win_line_endings(patch_paths.modification)
    _ensure_win_line_endings(patch_paths.deletion)
    _ensure_win_line_endings(patch_paths.diff)

    apply_patch(str(tmp_path), patch_paths.diff, testing_config)

    assert patch_paths.modification.read_bytes() == b"43770\r\n"
