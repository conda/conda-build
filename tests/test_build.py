# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This file tests the build.py module.  It sits lower in the stack than the API tests,
and is more unit-test oriented.
"""
import json
import os
import sys
from pathlib import Path

from conda.common.compat import on_win

from conda_build import api, build

from .utils import get_noarch_python_meta, metadata_dir

PREFIX_TESTS = {"normal": os.path.sep}
if on_win:
    PREFIX_TESTS.update({"double_backslash": "\\\\", "forward_slash": "/"})


def test_find_prefix_files(testing_workdir):
    """
    Write test output that has the prefix to be found, then verify that the prefix finding
    identified the correct number of files.
    """
    # create text files to be replaced
    files = []
    for style, replacement in PREFIX_TESTS.items():
        filename = Path(testing_workdir, f"{style}.txt")
        filename.write_text(testing_workdir.replace(os.path.sep, replacement))
        files.append(str(filename))

    assert len(list(build.have_prefix_files(files, testing_workdir))) == len(files)


def test_build_preserves_PATH(testing_config):
    m = api.render(os.path.join(metadata_dir, "source_git"), config=testing_config)[0][
        0
    ]
    ref_path = os.environ["PATH"]
    build.build(m, stats=None)
    assert os.environ["PATH"] == ref_path


def test_sanitize_channel():
    test_url = "https://conda.anaconda.org/t/ms-534991f2-4123-473a-b512-42025291b927/somechannel"
    assert build.sanitize_channel(test_url) == "https://conda.anaconda.org/somechannel"
    test_url_auth = "https://myuser:mypass@conda.anaconda.org/somechannel"
    assert (
        build.sanitize_channel(test_url_auth)
        == "https://conda.anaconda.org/somechannel"
    )


def test_get_short_path(testing_metadata):
    # Test for regular package
    assert build.get_short_path(testing_metadata, "test/file") == "test/file"

    # Test for noarch: python
    meta = get_noarch_python_meta(testing_metadata)
    assert build.get_short_path(meta, "lib/site-packages/test") == "site-packages/test"
    assert build.get_short_path(meta, "bin/test") == "python-scripts/test"
    assert build.get_short_path(meta, "Scripts/test") == "python-scripts/test"


def test_has_prefix():
    files_with_prefix = [
        ("prefix/path", "text", "short/path/1"),
        ("prefix/path", "text", "short/path/2"),
    ]
    assert build.has_prefix("short/path/1", files_with_prefix) == (
        "prefix/path",
        "text",
    )
    assert build.has_prefix("short/path/nope", files_with_prefix) == (None, None)


def test_is_no_link():
    no_link = ["path/1", "path/2"]
    assert build.is_no_link(no_link, "path/1") is True
    assert build.is_no_link(no_link, "path/nope") is None


def test_sorted_inode_first_path(testing_workdir):
    path_one = Path(testing_workdir, "one")
    path_two = Path(testing_workdir, "two")
    path_hardlink = Path(testing_workdir, "one_hl")

    path_one.touch()
    path_two.touch()
    os.link(path_one, path_hardlink)

    files = ["one", "two", "one_hl"]
    assert build.get_inode_paths(files, "one", testing_workdir) == ["one", "one_hl"]
    assert build.get_inode_paths(files, "one_hl", testing_workdir) == ["one", "one_hl"]
    assert build.get_inode_paths(files, "two", testing_workdir) == ["two"]


def test_create_info_files_json(testing_workdir, testing_metadata):
    info_dir = Path(testing_workdir, "info")
    info_dir.mkdir()
    Path(testing_workdir, "one").touch()
    Path(testing_workdir, "two").touch()
    Path(testing_workdir, "foo").touch()

    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "foo"]
    build.create_info_files_json_v1(
        testing_metadata, info_dir, testing_workdir, files, files_with_prefix
    )

    assert json.loads((info_dir / "paths.json").read_text()) == {
        "paths": [
            {
                "file_mode": "text",
                "path_type": "hardlink",
                "_path": "foo",
                "prefix_placeholder": "prefix/path",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "one",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "two",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
        ],
        "paths_version": 1,
    }


def test_create_info_files_json_symlinks(testing_workdir, testing_metadata):
    info_dir = Path(testing_workdir, "info")
    info_dir.mkdir()
    path_one = Path(testing_workdir, "one")
    path_two = Path(testing_workdir, "two")
    path_three = Path(testing_workdir, "three")  # do not make this one
    path_foo = Path(testing_workdir, "foo")
    path_two_symlink = Path(testing_workdir, "two_sl")
    symlink_to_nowhere = Path(testing_workdir, "nowhere_sl")
    recursive_symlink = Path(testing_workdir, "recursive_sl")
    cycle1_symlink = Path(testing_workdir, "cycle1_sl")
    cycle2_symlink = Path(testing_workdir, "cycle2_sl")

    path_one.touch()
    path_two.touch()
    path_foo.touch()
    os.symlink(path_two, path_two_symlink)
    os.symlink(path_three, symlink_to_nowhere)

    # make some recursive links
    os.symlink(path_two_symlink, recursive_symlink)
    os.symlink(cycle1_symlink, cycle2_symlink)
    os.symlink(cycle2_symlink, cycle1_symlink)

    files_with_prefix = [("prefix/path", "text", "foo")]
    files = [
        "one",
        "two",
        "foo",
        "two_sl",
        "nowhere_sl",
        "recursive_sl",
        "cycle1_sl",
        "cycle2_sl",
    ]

    build.create_info_files_json_v1(
        testing_metadata, info_dir, testing_workdir, files, files_with_prefix
    )
    assert json.loads((info_dir / "paths.json").read_text()) == {
        "paths": [
            {
                "path_type": "softlink",
                "_path": "cycle1_sl",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "softlink",
                "_path": "cycle2_sl",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "file_mode": "text",
                "path_type": "hardlink",
                "_path": "foo",
                "prefix_placeholder": "prefix/path",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "softlink",
                "_path": "nowhere_sl",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "one",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "softlink",
                "_path": "recursive_sl",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "two",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "softlink",
                "_path": "two_sl",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
        ],
        "paths_version": 1,
    }


def test_create_info_files_json_no_inodes(testing_workdir, testing_metadata):
    info_dir = Path(testing_workdir, "info")
    info_dir.mkdir()
    path_one = Path(testing_workdir, "one")
    path_two = Path(testing_workdir, "two")
    path_foo = Path(testing_workdir, "foo")
    path_one_hardlink = Path(testing_workdir, "one_hl")

    path_one.touch()
    path_two.touch()
    path_foo.touch()
    os.link(path_one, path_one_hardlink)

    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "one_hl", "foo"]
    build.create_info_files_json_v1(
        testing_metadata, info_dir, testing_workdir, files, files_with_prefix
    )
    assert json.loads((info_dir / "paths.json").read_text()) == {
        "paths": [
            {
                "file_mode": "text",
                "path_type": "hardlink",
                "_path": "foo",
                "prefix_placeholder": "prefix/path",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "one",
                "inode_paths": ["one", "one_hl"],
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "one_hl",
                "inode_paths": ["one", "one_hl"],
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
            {
                "path_type": "hardlink",
                "_path": "two",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_in_bytes": 0,
            },
        ],
        "paths_version": 1,
    }


def test_rewrite_output(testing_config, capsys):
    api.build(os.path.join(metadata_dir, "_rewrite_env"), config=testing_config)
    captured = capsys.readouterr()
    stdout = captured.out
    if sys.platform == "win32":
        assert "PREFIX=%PREFIX%" in stdout
        assert "LIBDIR=%PREFIX%\\lib" in stdout
        assert "PWD=%SRC_DIR%" in stdout
        assert "BUILD_PREFIX=%BUILD_PREFIX%" in stdout
    else:
        assert "PREFIX=$PREFIX" in stdout
        assert "LIBDIR=$PREFIX/lib" in stdout
        assert "PWD=$SRC_DIR" in stdout
        assert "BUILD_PREFIX=$BUILD_PREFIX" in stdout
