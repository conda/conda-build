import os

from pkg_resources import parse_version
import pytest
import yaml

from conda_build import api

thisdir = os.path.dirname(os.path.realpath(__file__))

repo_packages = [('', 'pypi', 'pip', "8.1.2"),
                 ('r', 'cran', 'nmf', ""),
                 ('r', 'cran', 'https://github.com/twitter/AnomalyDetection.git', ""),
                 ('perl', 'cpan', 'Moo', ""),
                 # ('lua', luarocks', 'LuaSocket'),
                 ]


@pytest.mark.parametrize("prefix,repo,package, version", repo_packages)
def test_repo(prefix, repo, package, version, testing_workdir, test_config):
    api.skeletonize(package, repo, version=version, output_dir=testing_workdir, config=test_config)
    try:
        base_package, _ = os.path.splitext(os.path.basename(package))
        package_name = "-".join([prefix, base_package]) if prefix else base_package
        assert os.path.isdir(os.path.join(testing_workdir, package_name.lower()))
    except:
        print(os.listdir(testing_workdir))
        raise


def test_name_with_version_specified(testing_workdir, test_config):
    api.skeletonize(packages='sympy', repo='pypi', version='0.7.5', config=test_config)
    with open('{}/test-skeleton/sympy-0.7.5/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('sympy/meta.yaml') as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)


def test_pypi_url(testing_workdir, test_config):
    api.skeletonize('https://pypi.python.org/packages/source/s/sympy/'
                    'sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9',
                    repo='pypi', config=test_config)
    with open('{}/test-skeleton/sympy-0.7.5-url/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('sympy/meta.yaml') as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)


def test_pypi_with_setup_options(testing_workdir, test_config):
    # Use photutils package below because skeleton will fail unless the setup.py is given
    # the flag --offline because of a bootstrapping a helper file that
    # occurs by default.

    # Test that the setup option is used in constructing the skeleton.
    api.skeletonize(packages='photutils', repo='pypi', version='0.2.2', setup_options='--offline',
                    config=test_config)

    # Check that the setup option occurs in bld.bat and build.sh.
    for script in ['bld.bat', 'build.sh']:
        with open('photutils/{}'.format(script)) as f:
            content = f.read()
            assert '--offline' in content


def test_pypi_pin_numpy(testing_workdir, test_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(packages='msumastro', repo='pypi', version='0.9.0', config=test_config,
                    pin_numpy=True)

    with open('msumastro/meta.yaml') as f:
        actual = yaml.load(f)

    assert 'numpy x.x' in actual['requirements']['run']
    assert 'numpy x.x' in actual['requirements']['build']


def test_pypi_version_sorting(testing_workdir, test_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(packages='impyla', repo='pypi', config=test_config)

    with open('impyla/meta.yaml') as f:
        actual = yaml.load(f)
        assert parse_version(actual['package']['version']) >= parse_version("0.13.8")


def test_list_skeletons():
    skeletons = api.list_skeletons()
    assert set(skeletons) == set(['pypi', 'cran', 'cpan', 'luarocks'])


def test_pypi_with_entry_points(testing_workdir):
    api.skeletonize('planemo', repo='pypi', python_version="2.7")
    assert os.path.isdir('planemo')


def test_pypi_with_version_arg(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/1442
    api.skeletonize('PrettyTable', 'pypi', version='0.7.2')
    with open('prettytable/meta.yaml') as f:
        actual = yaml.load(f)
        assert parse_version(actual['package']['version']) == parse_version("0.7.2")
