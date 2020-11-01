from collections import defaultdict
import os
import sys

import pytest

from conda_build.config import Config
from conda_build.variants import get_default_variant
from conda_build.metadata import MetaData
from conda_build.utils import check_call_env, prepend_bin_path, copy_into


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
                copy_into(str(f), os.path.join(saved_path, 'prof', f.basename))
        os.chdir(saved_path)

    request.addfinalizer(return_to_saved_path)

    return str(tmpdir)


@pytest.fixture(scope='function')
def testing_homedir(tmpdir, request):
    """ Create a homedir in the users home directory; cd into dir above before test, cd out after

    :param tmpdir: py.test fixture, will be injected
    :param request: py.test fixture-related, will be injected (see pytest docs)
    """

    saved_path = os.getcwd()
    d1 = os.path.basename(tmpdir)
    d2 = os.path.basename(os.path.dirname(tmpdir))
    d3 = os.path.basename(os.path.dirname(os.path.dirname(tmpdir)))
    new_dir = os.path.join(os.path.expanduser('~'), d1, d2, d3, 'pytest.conda-build')
    # While pytest will make sure a folder in unique
    if os.path.exists(new_dir):
        import shutil
        try:
            shutil.rmtree(new_dir)
        except:
            pass
    try:
        os.makedirs(new_dir)
    except:
        print("Failed to create {}".format(new_dir))
        return None
    os.chdir(new_dir)

    def return_to_saved_path():
        os.chdir(saved_path)

    request.addfinalizer(return_to_saved_path)

    return str(new_dir)


@pytest.fixture(scope='function')
def testing_config(testing_workdir):
    result = Config(croot=testing_workdir, anaconda_upload=False, verbose=True,
                    activate=False, debug=False, variant=None, test_run_post=False)
    # Tweak things that, for example, may come from ~/.condarc
    # (Setting()'s that use cc_conda_build.get for example).
    result.no_rewrite_stdout_env = False
    return result


@pytest.fixture(scope='function')
def testing_metadata(request, testing_config):
    d = defaultdict(dict)
    d['package']['name'] = request.function.__name__
    d['package']['version'] = '1.0'
    d['build']['number'] = '1'
    d['build']['entry_points'] = []
    d['requirements']['build'] = []
    d['requirements']['run'] = []
    d['test']['commands'] = ['echo "A-OK"', 'exit 0']
    d['about']['home'] = "sweet home"
    d['about']['license'] = "contract in blood"
    d['about']['summary'] = "a test package"
    d['about']['tags'] = ['a', 'b']
    d['about']['identifiers'] = 'a'
    testing_config.variant = get_default_variant(testing_config)
    testing_config.variants = [testing_config.variant]
    return MetaData.fromdict(d, config=testing_config)


@pytest.fixture(scope='function')
def testing_env(testing_workdir, request, monkeypatch):
    env_path = os.path.join(testing_workdir, 'env')

    check_call_env(['conda', 'create', '-yq', '-p', env_path,
                    'python={0}'.format(".".join(sys.version.split('.')[:2]))])
    monkeypatch.setenv('PATH', prepend_bin_path(os.environ.copy(), env_path,
                                                prepend_prefix=True)['PATH'])
    # cleanup is done by just cleaning up the testing_workdir
    return env_path


# these are functions so that they get regenerated each time we use them.
#    They could be fixtures, I guess.
@pytest.fixture(scope='function')
def numpy_version_ignored():
    return {"python": ["2.7.*", "3.5.*"],
            "numpy": ["1.10.*", "1.11.*"],
            "ignore_version": ['numpy']}


@pytest.fixture(scope='function')
def single_version():
    return {"python": "2.7.*", "numpy": "1.11.*"}


@pytest.fixture(scope='function')
def no_numpy_version():
    return {"python": ["2.7.*", "3.5.*"]}
