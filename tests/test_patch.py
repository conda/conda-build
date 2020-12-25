import os
import tempfile

import pytest

from conda_build.source import (_ensure_unix_line_endings, _ensure_win_line_endings,
                                _guess_patch_strip_level, apply_patch)
from conda_build.utils import on_win


def test_patch_strip_level(testing_workdir, monkeypatch):
    patchfiles = set(('some/common/prefix/one.txt',
                      'some/common/prefix/two.txt',
                      'some/common/prefix/three.txt'))
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
def patch_files(testing_workdir):
    with open('file-deletion.txt', 'w') as f:
        f.write('hello\n')
    with open('file-modification.txt', 'w') as f:
        f.write('hello\n')
    patchfile = 'patch'
    with open(patchfile, 'w') as f:
        f.write('diff file-deletion.txt file-deletion.txt\n')
        f.write('--- file-deletion.txt	2016-06-07 21:55:59.549798700 +0100\n')
        f.write('+++ file-deletion.txt	1970-01-01 01:00:00.000000000 +0100\n')
        f.write('@@ -1 +0,0 @@\n')
        f.write('-hello\n')
        f.write('diff file-creation.txt file-creation.txt\n')
        f.write('--- file-creation.txt	1970-01-01 01:00:00.000000000 +0100\n')
        f.write('+++ file-creation.txt	2016-06-07 21:55:59.549798700 +0100\n')
        f.write('@@ -0,0 +1 @@\n')
        f.write('+hello\n')
        f.write('diff file-modification.txt file-modification.txt.new\n')
        f.write('--- file-modification.txt	2016-06-08 18:23:08.384136600 +0100\n')
        f.write('+++ file-modification.txt.new	2016-06-08 18:23:37.565136200 +0100\n')
        f.write('@@ -1 +1 @@\n')
        f.write('-hello\n')
        f.write('+43770\n')
    return patchfile


# TODO :: These should require a build env with patch (or m2-patch) in it.
#         at present, ci/azurepipelines/install_conda_build_test_deps installs
#         this.
def test_patch(patch_files, testing_config_with_patch):
    apply_patch('.', patch_files, testing_config_with_patch)
    assert not os.path.exists('file-deletion.txt')
    assert os.path.exists('file-creation.txt')
    assert os.path.exists('file-modification.txt')
    with open('file-modification.txt', 'r') as modified:
        lines = modified.readlines()
    assert lines[0] == '43770\n'


def test_ensure_unix_line_endings_with_nonutf8_characters():
    in_path = tempfile.mktemp()
    with open(in_path, "wb") as fp:
        fp.write(b"\xf1\r\n")  # tilde-n encoded in latin1

    out_path = _ensure_unix_line_endings(in_path)
    with open(out_path, "rb") as fp:
        assert fp.read() == b"\xf1\n"

    os.remove(in_path)
    os.remove(out_path)


def test_patch_unix_source_win_patch(patch_files, testing_config):
    _ensure_unix_line_endings('file-modification.txt')
    _ensure_win_line_endings(patch_files)
    apply_patch('.', patch_files, testing_config)
    with open('file-modification.txt', 'r') as modified:
        lines = modified.readlines()
    assert lines[0] == '43770\n'


def test_patch_win_source_unix_patch(patch_files, testing_config):
    _ensure_win_line_endings('file-modification.txt')
    _ensure_unix_line_endings(patch_files)
    apply_patch('.', patch_files, testing_config)
    with open('file-modification.txt', 'r') as modified:
        lines = modified.readlines()
    assert lines[0] == '43770\n'
