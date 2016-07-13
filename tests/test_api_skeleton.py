import os

import pytest
import yaml

from conda_build import api
from .utils import testing_workdir, test_config

thisdir = os.path.dirname(os.path.realpath(__file__))

repo_packages = [('', 'pypi', 'pip', "8.1.2"),
                 ('r', 'cran', 'nmf', ""),
                 ('perl', 'cpan', 'Struct-Path', ""),
                 # ('lua', luarocks', 'LuaSocket'),
                 ]


@pytest.mark.parametrize("prefix,repo,package, version", repo_packages)
def test_repo(prefix, repo, package, version, testing_workdir, test_config):
    api.skeletonize(package, output_dir=testing_workdir, repo=repo, config=test_config)
    try:
        package_name = "-".join([prefix, package]) if prefix else package
        assert os.path.isdir(os.path.join(testing_workdir, package_name.lower()))
    except:
        print(os.listdir(testing_workdir))
        raise

def test_name_with_version_specified(testing_workdir, test_config):
    api.skeletonize('sympy', 'pypi', version='0.7.5', config=test_config)
    with open('{}/test-skeleton/sympy-0.7.5/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('sympy/meta.yaml') as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)


def test_pypi_url(testing_workdir, test_config):
    api.skeletonize('https://pypi.io/packages/source/s/sympy/'
                    'sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9',
                    'pypi', config=test_config)
    with open('{}/test-skeleton/sympy-0.7.5-url/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('sympy/meta.yaml') as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)
