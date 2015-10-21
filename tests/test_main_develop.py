'''
Simple tests for testing functions in main_develop module
'''
import os
import shutil
from os.path import dirname, join, exists

from conda_build.main_develop import uninstall, write_to_conda_pth

import pytest


@pytest.fixture(scope="session")
def sp_dir(request):
    '''
    create site-packges/ directory in same place where test is located. This
    is where tests look conda.pth file. It is a session scoped fixture and
    it has a finalizer function invoked in the end to remove site-packages/
    directory
    '''
    base_dir = dirname(__file__)
    sp = join(base_dir, 'site-packages')
    if exists(sp):
        shutil.rmtree(sp)

    os.mkdir(sp)

    def cleanup():
        # session scoped cleanup is called at end of the session
        shutil.rmtree(sp)

    request.addfinalizer(cleanup)

    return sp


@pytest.fixture(scope="function")
def conda_pth(sp_dir):
    '''
    Returns the path to conda.pth - though we don't expect name to change
    from conda.pth, better to keep this in one place

    Removes 'conda.pth' if it exists so each test starts without a conda.pth
    file
    '''
    pth = join(sp_dir, 'conda.pth')
    if exists(pth):
        os.remove(pth)

    return pth


# Note: following list is data used for testing - do not change it
_path_in_dev_mode = ['/Users/jsandhu/Documents/projects/CythonExample',
                     '/Users/jsandhu/Documents/projects/TestOne',
                     '/Users/jsandhu/Documents/projects/TestOne',
                     '/Users/jsandhu/Documents/projects/TestTwo']

# following list of tuples contains the path and the number of lines
# added/remaining after invoking develop/uninstall.
# These are used to make assertions
_toadd_and_num_after_install = zip(_path_in_dev_mode, (1, 2, 2, 3))
_torm_and_num_after_uninstall = zip(_path_in_dev_mode, (2, 1, 1, 0))


def test_write_to_conda_pth(sp_dir, conda_pth):
    '''
    `conda develop pkg_path` invokes write_to_conda_pth() to write/append to
    conda.pth - this is a basic unit test for write_to_conda_pth

    :param str sp_dir: path to site-packages directory returned by fixture
    :param str conda_pth: path to conda.pth returned by fixture
    '''
    assert not exists(conda_pth)

    for pth, exp_num_pths in _toadd_and_num_after_install:
        write_to_conda_pth(sp_dir, pth)
        assert exists(conda_pth)
        # write to path twice but ensure it only gets written to fine once
        write_to_conda_pth(sp_dir, pth)
        with open(conda_pth, 'r') as f:
            lines = f.readlines()
            assert (pth + '\n') in lines
            assert len(lines) == exp_num_pths


def test_uninstall(sp_dir, conda_pth, request):
    '''
    `conda develop --uninstall pkg_path` invokes uninstall() to remove path
    from conda.pth - this is a unit test for uninstall

    It also includes a cleanup function that deletes the conda.pth file

    :param str sp_dir: path to site-packages directory returned by fixture
    :param str conda_pth: path to conda.pth returned by fixture
    '''
    # first write data in conda.pth if it doesn't yet exist
    # if all tests are invoked, then conda.pth exists
    if not exists(conda_pth):
        for pth in _path_in_dev_mode:
            write_to_conda_pth(sp_dir, pth)

    for to_rm, exp_num_pths in _torm_and_num_after_uninstall:
        # here's where the testing begins
        uninstall(sp_dir, to_rm)
        assert exists(conda_pth)

        with open(conda_pth, 'r') as f:
            lines = f.readlines()
            assert to_rm + '\n' not in lines
            assert len(lines) == exp_num_pths
