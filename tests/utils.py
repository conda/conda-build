from collections import defaultdict
import os
import subprocess
import sys
import tarfile

import pytest

from conda_build.conda_interface import PY3
from conda_build.config import Config
from conda_build.metadata import MetaData
from conda_build.utils import on_win, prepend_bin_path

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, "test-recipes/metadata")
fail_dir = os.path.join(thisdir, "test-recipes/fail")


def is_valid_dir(parent_dir, dirname):
    valid = os.path.isdir(os.path.join(parent_dir, dirname))
    valid &= not dirname.startswith("_")
    valid &= ('osx_is_app' != dirname or sys.platform == "darwin")
    return valid


@pytest.fixture(scope='function')
def testing_workdir(tmpdir, request):
    """ Create a workdir in a safe temporary folder; cd into dir above before test, cd out after

    :param tmpdir: py.test fixture, will be injected
    :param request: py.test fixture-related, will be injected (see pytest docs)
    """

    saved_path = os.getcwd()

    tmpdir.chdir()
    # temporary folder for profiling output, if any
    tmpdir.mkdir('prof')

    def return_to_saved_path():
        if os.path.isdir(os.path.join(saved_path, 'prof')):
            profdir = tmpdir.join('prof')
            files = profdir.listdir('*.prof') if profdir.isdir() else []

            for f in files:
                f.rename(os.path.join(saved_path, 'prof', f.basename))
        os.chdir(saved_path)

    request.addfinalizer(return_to_saved_path)

    return str(tmpdir)


@pytest.fixture(scope='function')
def test_config(testing_workdir, request):
    return Config(croot=testing_workdir, anaconda_upload=False, verbose=True)


@pytest.fixture(scope='function')
def test_metadata(request, test_config):
    d = defaultdict(dict)
    d['package']['name'] = request.function.__name__
    d['package']['version'] = '1.0'
    d['build']['number'] = '1'
    d['build']['entry_points'] = []
    # MetaData does the auto stuff if the build string is None
    d['build']['string'] = None
    d['requirements']['build'] = ['python']
    d['requirements']['run'] = ['python']
    d['test']['commands'] = ['echo "A-OK"', 'exit 0']
    d['about']['home'] = "sweet home"
    d['about']['license'] = "contract in blood"
    d['about']['summary'] = "a test package"

    return MetaData.fromdict(d, config=test_config)


@pytest.fixture(scope='function')
def testing_env(testing_workdir, request):
    env_path = os.path.join(testing_workdir, 'env')

    subprocess.check_call(['conda', 'create', '-yq', '-p', env_path,
                           'python={0}'.format(".".join(sys.version.split('.')[:2]))])
    path_backup = os.environ['PATH']
    os.environ['PATH'] = prepend_bin_path(os.environ.copy(), env_path, prepend_prefix=True)['PATH']

    # cleanup is done by just cleaning up the testing_workdir
    def reset_path():
        os.environ['PATH'] = path_backup

    request.addfinalizer(reset_path)
    return env_path


def add_mangling(filename):
    if PY3:
        filename = os.path.splitext(filename)[0] + '.cpython-{0}{1}.py'.format(
            sys.version_info.major, sys.version_info.minor)
        filename = os.path.join(os.path.dirname(filename), '__pycache__',
                                os.path.basename(filename))
    return filename + 'c'
