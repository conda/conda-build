from collections import defaultdict
import os
import sys

import pytest

from conda_build.config import Config
from conda_build.index import get_build_index
from conda_build.conda_interface import subdir
from conda_build.variants import get_default_variants
from conda_build.metadata import MetaData
from conda_build.render import finalize_metadata
from conda_build.utils import check_call_env, prepend_bin_path, capture


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
def testing_index(request):
    index = get_build_index(config=Config(debug=False, verbose=False), subdir=subdir, clear_cache=True)
    return index


@pytest.fixture(scope='function')
def testing_config(testing_workdir, testing_index, request):
    return Config(croot=testing_workdir, anaconda_upload=False, verbose=True,
                  activate=False, debug=False, variant=get_default_variants()[0],
                  indexes=testing_index)


@pytest.fixture(scope='function')
def testing_metadata(request, testing_config, testing_index):
    d = defaultdict(dict)
    d['package']['name'] = request.function.__name__
    d['package']['version'] = '1.0'
    d['build']['number'] = '1'
    d['build']['entry_points'] = []
    d['requirements']['build'] = ['python']
    d['requirements']['run'] = ['python']
    d['test']['commands'] = ['echo "A-OK"', 'exit 0']
    d['about']['home'] = "sweet home"
    d['about']['license'] = "contract in blood"
    d['about']['summary'] = "a test package"
    testing_config.index = testing_index
    testing_config.variant = get_default_variants()[0]
    return finalize_metadata(MetaData.fromdict(d, config=testing_config), index=testing_index)


@pytest.fixture(scope='function')
def testing_env(testing_workdir, request):
    env_path = os.path.join(testing_workdir, 'env')

    check_call_env(['conda', 'create', '-yq', '-p', env_path,
                    'python={0}'.format(".".join(sys.version.split('.')[:2]))])
    path_backup = os.environ['PATH']
    os.environ['PATH'] = prepend_bin_path(os.environ.copy(), env_path, prepend_prefix=True)['PATH']

    # cleanup is done by just cleaning up the testing_workdir
    def reset_path():
        os.environ['PATH'] = path_backup

    request.addfinalizer(reset_path)
    return env_path
