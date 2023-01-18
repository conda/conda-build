# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
from os.path import join
from pathlib import Path

import pytest
from conda_build.utils import on_win
from conda_build._link import pyc_f
from conda_build.conda_interface import PathType, EntityEncoder, CrossPlatformStLink


@pytest.mark.parametrize(
    "source,python,compiled",
    [
        ("path/utils.py", (2, 7), "path/utils.pyc"),
        ("pa/th/utils.py", (2, 7), "pa/th/utils.pyc"),
        ("path/utils.py", (3, 10), "path/__pycache__/utils.cpython-310.pyc"),
        ("pa/th/utils.py", (3, 10), "pa/th/__pycache__/utils.cpython-310.pyc"),
    ],
)
def test_pyc_f(source, python, compiled):
    assert Path(pyc_f(source, python)) == Path(compiled)


def test_pathtype():
    hardlink = PathType("hardlink")
    assert str(hardlink) == "hardlink"
    assert hardlink.__json__() == 'hardlink'

    softlink = PathType("softlink")
    assert str(softlink) == "softlink"
    assert softlink.__json__() == "softlink"


def test_entity_encoder(tmpdir):
    test_file = join(str(tmpdir), "test-file")
    test_json = {"a": PathType("hardlink"), "b": 1}
    with open(test_file, "w") as f:
        json.dump(test_json, f, cls=EntityEncoder)

    with open(test_file) as f:
        json_file = json.load(f)
    assert json_file == {"a": "hardlink", "b": 1}


@pytest.mark.skipif(on_win, reason="link not available on win/py2.7")
def test_crossplatform_st_link(tmpdir):
    from os import link
    test_file = join(str(tmpdir), "test-file")
    test_file_linked = join(str(tmpdir), "test-file-linked")
    test_file_link = join(str(tmpdir), "test-file-link")

    open(test_file, "a").close()
    open(test_file_link, "a").close()
    link(test_file_link, test_file_linked)
    assert 1 == CrossPlatformStLink.st_nlink(test_file)
    assert 2 == CrossPlatformStLink.st_nlink(test_file_link)
    assert 2 == CrossPlatformStLink.st_nlink(test_file_linked)


@pytest.mark.skipif(not on_win, reason="already tested")
def test_crossplatform_st_link_on_win(tmpdir):
    test_file = join(str(tmpdir), "test-file")
    open(test_file, "a").close()
    assert 1 == CrossPlatformStLink.st_nlink(test_file)
