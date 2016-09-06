import os
import shutil
import sys

from conda_build.conda_interface import TemporaryDirectory, PY3
import pytest

from conda_build import post
from conda_build.utils import on_win

from .utils import test_config, testing_workdir, add_mangling


def test_compile_missing_pyc(testing_workdir):
    good_files = ['f1.py', 'f3.py']
    bad_file = 'f2_bad.py'
    tmp = os.path.join(testing_workdir, 'tmp')
    shutil.copytree(os.path.join(os.path.dirname(__file__), 'test-recipes',
                                 'metadata', '_compile-test'), tmp)
    post.compile_missing_pyc(os.listdir(tmp), cwd=tmp,
                                python_exe=sys.executable)
    for f in good_files:
        assert os.path.isfile(os.path.join(tmp, add_mangling(f)))
    assert not os.path.isfile(os.path.join(tmp, add_mangling(bad_file)))


@pytest.mark.skipif(on_win, reason="no linking on win")
def test_hardlinks_to_copies(testing_workdir):
    with open('test1', 'w') as f:
        f.write("\n")

    os.link('test1', 'test2')
    assert os.lstat('test1').st_nlink == 2
    assert os.lstat('test2').st_nlink == 2

    post.make_hardlink_copy('test1', os.getcwd())
    post.make_hardlink_copy('test2', os.getcwd())

    assert os.lstat('test1').st_nlink == 1
    assert os.lstat('test2').st_nlink == 1
