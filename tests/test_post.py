import os
import shutil
import sys

from conda.compat import TemporaryDirectory, PY3
import pytest

from conda_build import post
from conda_build.utils import on_win


def test_compile_missing_pyc():
    cwd = os.getcwd()
    good_files = ['f1.py', 'f3.py']
    bad_file = 'f2_bad.py'
    with TemporaryDirectory() as tmp:
        tmpdir = os.path.join(tmp, 'files')
        shutil.copytree(os.path.join(os.path.dirname(__file__), 'test-recipes',
                                     'metadata', '_compile-test'),
                        tmpdir)
        os.chdir(tmpdir)
        try:
            post.compile_missing_pyc(os.listdir(tmpdir), cwd=tmpdir, python_exe=sys.executable)
            files = os.listdir(tmpdir)
            for f in good_files:
                assert f + 'c' in files
            assert bad_file + 'c' not in files
        except:
            raise
        finally:
            os.chdir(cwd)


@pytest.mark.skipif(not PY3, reason="test applies to py3 only")
def test_coerce_pycache_to_old_style():
    cwd = os.getcwd()
    with TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, '__pycache__'))
        os.makedirs(os.path.join(tmp, 'testdir', '__pycache__'))
        with open(os.path.join(tmp, 'test.py'), 'w') as f:
            f.write("\n")
        with open(os.path.join(tmp, '__pycache__', 'test.cpython-{0}{1}.pyc'.format(
                sys.version_info.major, sys.version_info.minor)), 'w') as f:
            f.write("\n")
        with open(os.path.join(tmp, 'testdir', 'test.py'), 'w') as f:
            f.write("\n")
        with open(os.path.join(tmp, 'testdir', '__pycache__', 'test.cpython-{0}{1}.pyc'.format(
                sys.version_info.major, sys.version_info.minor)), 'w') as f:
            f.write("\n")

        os.chdir(tmp)
        for root, dirs, files in os.walk(tmp):
            fs = [os.path.join(root, _) for _ in files]
            post.coerce_pycache_to_old_style(fs, cwd=tmp)
        try:
            assert os.path.isfile(os.path.join(tmp, 'test.pyc')), os.listdir(tmp)
            assert os.path.isfile(os.path.join(tmp, 'testdir', 'test.pyc')), \
                os.listdir(os.path.join(tmp, 'testdir'))
            for root, dirs, files in os.walk(tmp):
                assert '__pycache__' not in dirs
        except:
            raise
        finally:
            os.chdir(cwd)


@pytest.mark.skipif(on_win, reason="no linking on win")
def test_hardlinks_to_copies():
    with open('test1', 'w') as f:
        f.write("\n")
    try:
        os.link('test1', 'test2')
        assert os.lstat('test1').st_nlink == 2
        assert os.lstat('test2').st_nlink == 2

        post.make_hardlink_copy('test1')
        post.make_hardlink_copy('test2')

        assert os.lstat('test1').st_nlink == 1
        assert os.lstat('test2').st_nlink == 1
    except:
        raise
    finally:
        os.remove('test1')
        if os.path.exists('test2'):
            os.remove('test2')
