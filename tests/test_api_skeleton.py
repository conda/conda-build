import os

from pkg_resources import parse_version
import pytest
import yaml

from conda_build import api
from .utils import testing_workdir, test_config

thisdir = os.path.dirname(os.path.realpath(__file__))

repo_packages = [('', 'pypi', 'pip', "8.1.2"),
                 ('r', 'cran', 'nmf', ""),
                 ('perl', 'cpan', 'Shell-Cmd', ""),
                 # ('lua', luarocks', 'LuaSocket'),
                 ]


@pytest.mark.parametrize("prefix,repo,package, version", repo_packages)
def test_repo(prefix, repo, package, version, testing_workdir, test_config):
    test_config.packages = package
    test_config.output_dir = testing_workdir
    test_config.version = version
    test_config.repo = repo
    api.skeletonize(config=test_config)
    try:
        package_name = "-".join([prefix, package]) if prefix else package
        assert os.path.isdir(os.path.join(testing_workdir, package_name.lower()))
    except:
        print(os.listdir(testing_workdir))
        raise

def test_name_with_version_specified(testing_workdir, test_config):
    test_config.packages = 'sympy'
    test_config.repo = 'pypi'
    test_config.version = '0.7.5'
    api.skeletonize(config=test_config)
    with open('{}/test-skeleton/sympy-0.7.5/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('sympy/meta.yaml') as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)


def test_pypi_url(testing_workdir, test_config):
    test_config.packages = 'https://pypi.python.org/packages/source/s/sympy/sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9'
    test_config.repo = 'pypi'
    api.skeletonize(config=test_config)
    with open('{}/test-skeleton/sympy-0.7.5-url/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('sympy/meta.yaml') as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)

def test_pypi_with_setup_options(testing_workdir, test_config):
    # Use package below because  skeleton will fail unless the setup.py is given
    # the flag --offline because of a bootstrapping a helper file that
    # occurs by default.

    # Test that the setup option is used in constructing the skeleton.
    test_config.packages = 'photutils'
    test_config.repo = 'pypi'
    test_config.version = '0.2.2'
    test_config.setup_options = "--offline"
    api.skeletonize(config=test_config)

    # Check that the setup option occurs in bld.bat and build.sh.
    for script in ['bld.bat', 'build.sh']:
        with open('photutils/{}'.format(script)) as f:
            content = f.read()
            assert '--offline' in content


def test_pypi_pin_numpy(testing_workdir, test_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    test_config.packages = 'msumastro'
    test_config.repo = 'pypi'
    test_config.version = '0.9.0'
    test_config.pin_numpy = True
    api.skeletonize(config=test_config)

    with open('msumastro/meta.yaml') as f:
        actual = yaml.load(f)

    assert 'numpy x.x' in actual['requirements']['run']
    assert 'numpy x.x' in actual['requirements']['build']


def test_pypi_version_sorting(testing_workdir, test_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    test_config.packages = 'impyla'
    test_config.repo = 'pypi'
    api.skeletonize(config=test_config)

    with open('impyla/meta.yaml') as f:
        actual = yaml.load(f)
        assert parse_version(actual['package']['version']) >= parse_version("0.13.8")


def test_list_skeletons():
    skeletons = api.list_skeletons()
    assert set(skeletons) == set(['pypi', 'cran', 'cpan', 'luarocks'])
