import os
import shutil
import sys

from conda_build.conda_interface import TemporaryDirectory, PY3
import pytest

from conda_build import post
from conda_build.utils import on_win

from .utils import test_config, testing_workdir


def test_compile_missing_pyc(testing_workdir):
    good_files = ['f1.py', 'f3.py']
    bad_file = 'f2_bad.py'
    tmp = os.path.join(testing_workdir, 'tmp')
    shutil.copytree(os.path.join(os.path.dirname(__file__), 'test-recipes',
                                 'metadata', '_compile-test'), tmp)
    post.compile_missing_pyc(os.listdir(tmp), cwd=tmp,
                                python_exe=sys.executable)
    files = os.listdir(tmp)
    for f in good_files:
        assert f + 'c' in files
    assert bad_file + 'c' not in files


@pytest.mark.skipif(not PY3, reason="test applies to py3 only")
def test_coerce_pycache_to_old_style(testing_workdir):
    os.makedirs(os.path.join(testing_workdir, '__pycache__'))
    os.makedirs(os.path.join(testing_workdir, 'testdir', '__pycache__'))
    with open(os.path.join(testing_workdir, 'test.py'), 'w') as f:
        f.write("\n")
    with open(os.path.join(testing_workdir, '__pycache__', 'test.cpython-{0}{1}.pyc'.format(
            sys.version_info.major, sys.version_info.minor)), 'w') as f:
        f.write("\n")
    with open(os.path.join(testing_workdir, 'testdir', 'test.py'), 'w') as f:
        f.write("\n")
    with open(os.path.join(testing_workdir, 'testdir', '__pycache__',
                           'test.cpython-{0}{1}.pyc'.format(
                               sys.version_info.major, sys.version_info.minor)), 'w') as f:
        f.write("\n")

    for root, dirs, files in os.walk(testing_workdir):
        fs = [os.path.join(root, _) for _ in files]
        post.coerce_pycache_to_old_style(fs, cwd=testing_workdir)
    assert os.path.isfile(os.path.join(testing_workdir, 'test.pyc')), os.listdir(testing_workdir)
    assert os.path.isfile(os.path.join(testing_workdir, 'testdir', 'test.pyc')), \
        os.listdir(os.path.join(testing_workdir, 'testdir'))
    for root, dirs, files in os.walk(testing_workdir):
        assert '__pycache__' not in dirs


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
