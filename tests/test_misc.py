import unittest
import json
from os.path import join

import pytest
from conda_build.utils import on_win
import conda_build._link as _link
from conda_build.conda_interface import PathType, EntityEncoder, CrossPlatformStLink


class TestLink(unittest.TestCase):

    def test_pyc_f_2(self):
        self.assertEqual(_link.pyc_f('sp/utils.py', (2, 7, 9)),
                                     'sp/utils.pyc')

    def test_pyc_f_3(self):
        for f, r in [
                ('sp/utils.py',
                 'sp/__pycache__/utils.cpython-34.pyc'),
                ('sp/foo/utils.py',
                 'sp/foo/__pycache__/utils.cpython-34.pyc'),
        ]:
            self.assertEqual(_link.pyc_f(f, (3, 4, 2)), r)


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

    with open(test_file, "r") as f:
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

