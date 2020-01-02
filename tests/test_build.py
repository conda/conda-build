"""
This file tests the build.py module.  It sits lower in the stack than the API tests,
and is more unit-test oriented.
"""

import json
import os
import sys

import pytest

from conda_build import build, api
from conda_build.utils import on_win

from .utils import metadata_dir, get_noarch_python_meta

prefix_tests = {"normal": os.path.sep}
if sys.platform == "win32":
    prefix_tests.update({"double_backslash": "\\\\",
                         "forward_slash": "/"})


def _write_prefix(filename, prefix, replacement):
    with open(filename, "w") as f:
        f.write(prefix.replace(os.path.sep, replacement))
        f.write("\n")


def test_find_prefix_files(testing_workdir):
    """
    Write test output that has the prefix to be found, then verify that the prefix finding
    identified the correct number of files.
    """
    # create text files to be replaced
    files = []
    for slash_style in prefix_tests:
        filename = os.path.join(testing_workdir, "%s.txt" % slash_style)
        _write_prefix(filename, testing_workdir, prefix_tests[slash_style])
        files.append(filename)

    assert len(list(build.have_prefix_files(files, testing_workdir))) == len(files)


def test_build_preserves_PATH(testing_workdir, testing_config):
    m = api.render(os.path.join(metadata_dir, 'source_git'), config=testing_config)[0][0]
    ref_path = os.environ['PATH']
    build.build(m, stats=None)
    assert os.environ['PATH'] == ref_path


def test_sanitize_channel():
    test_url = 'https://conda.anaconda.org/t/ms-534991f2-4123-473a-b512-42025291b927/somechannel'
    assert build.sanitize_channel(test_url) == 'https://conda.anaconda.org/t/<TOKEN>/somechannel'


def test_get_short_path(testing_metadata):
    # Test for regular package
    assert build.get_short_path(testing_metadata, "test/file") == "test/file"

    # Test for noarch: python
    meta = get_noarch_python_meta(testing_metadata)
    assert build.get_short_path(meta, "lib/site-packages/test") == "site-packages/test"
    assert build.get_short_path(meta, "bin/test") == "python-scripts/test"
    assert build.get_short_path(meta, "Scripts/test") == "python-scripts/test"


def test_has_prefix():
    files_with_prefix = [("prefix/path", "text", "short/path/1"),
                         ("prefix/path", "text", "short/path/2")]
    assert build.has_prefix("short/path/1", files_with_prefix) == ("prefix/path", "text")
    assert build.has_prefix("short/path/nope", files_with_prefix) == (None, None)


def test_is_no_link():
    no_link = ["path/1", "path/2"]
    assert build.is_no_link(no_link, "path/1") is True
    assert build.is_no_link(no_link, "path/nope") is None


@pytest.mark.skipif(on_win and sys.version[:3] == "2.7",
                    reason="os.link is not available so can't setup test")
def test_sorted_inode_first_path(testing_workdir):
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_one_hardlink = os.path.join(testing_workdir, "one_hl")
    open(path_one, "a").close()
    open(path_two, "a").close()

    os.link(path_one, path_one_hardlink)

    files = ["one", "two", "one_hl"]
    assert build.get_inode_paths(files, "one", testing_workdir) == ["one", "one_hl"]
    assert build.get_inode_paths(files, "one_hl", testing_workdir) == ["one", "one_hl"]
    assert build.get_inode_paths(files, "two", testing_workdir) == ["two"]


def test_create_info_files_json(testing_workdir, testing_metadata):
    info_dir = os.path.join(testing_workdir, "info")
    os.mkdir(info_dir)
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_foo = os.path.join(testing_workdir, "foo")
    open(path_one, "a").close()
    open(path_two, "a").close()
    open(path_foo, "a").close()
    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "foo"]

    build.create_info_files_json_v1(testing_metadata, info_dir, testing_workdir, files,
                                    files_with_prefix)
    files_json_path = os.path.join(info_dir, "paths.json")
    expected_output = {
        "paths": [{"file_mode": "text", "path_type": "hardlink", "_path": "foo",
                   "prefix_placeholder": "prefix/path",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "one",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "two",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0}],
        "paths_version": 1}
    with open(files_json_path, "r") as files_json:
        output = json.load(files_json)
        assert output == expected_output


@pytest.mark.skipif(on_win and sys.version[:3] == "2.7",
                    reason="os.symlink is not available so can't setup test")
def test_create_info_files_json_symlinks(testing_workdir, testing_metadata):
    info_dir = os.path.join(testing_workdir, "info")
    os.mkdir(info_dir)
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_three = os.path.join(testing_workdir, "three")  # do not make this one
    path_foo = os.path.join(testing_workdir, "foo")
    path_two_symlink = os.path.join(testing_workdir, "two_sl")
    symlink_to_nowhere = os.path.join(testing_workdir, "nowhere_sl")
    open(path_one, "a").close()
    open(path_two, "a").close()
    open(path_foo, "a").close()
    os.symlink(path_two, path_two_symlink)
    os.symlink(path_three, symlink_to_nowhere)
    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "foo", "two_sl", "nowhere_sl"]

    build.create_info_files_json_v1(testing_metadata, info_dir, testing_workdir, files,
                                    files_with_prefix)
    files_json_path = os.path.join(info_dir, "paths.json")
    expected_output = {
        "paths": [{"file_mode": "text", "path_type": "hardlink", "_path": "foo",
                   "prefix_placeholder": "prefix/path",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "softlink", "_path": "nowhere_sl",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "one",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "two",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "softlink", "_path": "two_sl",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0}],
        "paths_version": 1}
    with open(files_json_path, "r") as files_json:
        output = json.load(files_json)
        assert output == expected_output


@pytest.mark.skipif(on_win and sys.version[:3] == "2.7",
                    reason="os.link is not available so can't setup test")
def test_create_info_files_json_no_inodes(testing_workdir, testing_metadata):
    info_dir = os.path.join(testing_workdir, "info")
    os.mkdir(info_dir)
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_foo = os.path.join(testing_workdir, "foo")
    path_one_hardlink = os.path.join(testing_workdir, "one_hl")
    open(path_one, "a").close()
    open(path_two, "a").close()
    open(path_foo, "a").close()
    os.link(path_one, path_one_hardlink)
    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "one_hl", "foo"]

    build.create_info_files_json_v1(testing_metadata, info_dir, testing_workdir, files,
                                    files_with_prefix)
    files_json_path = os.path.join(info_dir, "paths.json")
    expected_output = {
        "paths": [{"file_mode": "text", "path_type": "hardlink", "_path": "foo",
                   "prefix_placeholder": "prefix/path",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "one", "inode_paths": ["one", "one_hl"],
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "one_hl", "inode_paths": ["one", "one_hl"],
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"path_type": "hardlink", "_path": "two",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0}],
        "paths_version": 1}
    with open(files_json_path, "r") as files_json:
        output = json.load(files_json)
        assert output == expected_output


def test_rewrite_output(testing_workdir, testing_config, capsys):
    api.build(os.path.join(metadata_dir, "_rewrite_env"), config=testing_config)
    captured = capsys.readouterr()
    stdout = captured.out
    if sys.platform == 'win32':
        assert "PREFIX=%PREFIX%" in stdout
        assert "LIBDIR=%PREFIX%\\lib" in stdout
        assert "PWD=%SRC_DIR%" in stdout
        assert "BUILD_PREFIX=%BUILD_PREFIX%" in stdout
    else:
        assert "PREFIX=$PREFIX" in stdout
        assert "LIBDIR=$PREFIX/lib" in stdout
        assert "PWD=$SRC_DIR" in stdout
        assert "BUILD_PREFIX=$BUILD_PREFIX" in stdout
