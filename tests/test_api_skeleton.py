import os
import sys

from pkg_resources import parse_version
import pytest

from conda_build import api
from conda_build.exceptions import DependencyNeedsBuildingError

thisdir = os.path.dirname(os.path.realpath(__file__))

repo_packages = [('', 'pypi', 'pip', '8.1.2'),
                 ('r', 'cran', 'nmf', ''),
                 ('r', 'cran', 'https://github.com/twitter/AnomalyDetection.git', ''),
                 ('perl', 'cpan', 'Moo', ''),
                 ('', 'rpm', 'libX11-devel', ''),
                 # ('lua', luarocks', 'LuaSocket', ''),
                 ]


@pytest.mark.serial
@pytest.mark.parametrize("prefix, repo, package, version", repo_packages)
def test_repo(prefix, repo, package, version, testing_workdir, testing_config):
    api.skeletonize(package, repo, version=version, output_dir=testing_workdir,
                    config=testing_config)
    try:
        base_package, _ = os.path.splitext(os.path.basename(package))
        package_name = "-".join([prefix, base_package]) if prefix else base_package
        contents = os.listdir(testing_workdir)
        assert len([content for content in contents
                    if content.startswith(package_name.lower()) and
                    os.path.isdir(os.path.join(testing_workdir, content))])
    except:
        print(os.listdir(testing_workdir))
        raise


@pytest.mark.serial
def test_name_with_version_specified(testing_workdir, testing_config):
    api.skeletonize(packages='sympy', repo='pypi', version='0.7.5', config=testing_config)
    m = api.render('sympy/meta.yaml')[0][0]
    assert m.version() == "0.7.5"


@pytest.mark.serial
def test_pypi_url(testing_workdir, testing_config):
    api.skeletonize('https://pypi.python.org/packages/source/s/sympy/'
                    'sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9',
                    repo='pypi', config=testing_config)
    m = api.render('sympy/meta.yaml')[0][0]
    assert m.version() == "0.7.5"


@pytest.mark.serial
def test_pypi_with_setup_options(testing_workdir, testing_config):
    # Use photutils package below because skeleton will fail unless the setup.py is given
    # the flag --offline because of a bootstrapping a helper file that
    # occurs by default.

    # Test that the setup option is used in constructing the skeleton.
    api.skeletonize(packages='photutils', repo='pypi', version='0.2.2', setup_options='--offline',
                    config=testing_config)

    # Check that the setup option occurs in bld.bat and build.sh.
    m = api.render('photutils')[0][0]
    assert '--offline' in m.meta['build']['script']


@pytest.mark.serial
def test_pypi_pin_numpy(testing_workdir, testing_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(packages='msumastro', repo='pypi', version='0.9.0', config=testing_config,
                    pin_numpy=True)
    with open(os.path.join('msumastro', 'meta.yaml')) as f:
        assert f.read().count('numpy x.x') == 2
    with pytest.raises(DependencyNeedsBuildingError):
        api.build('msumastro')


@pytest.mark.serial
def test_pypi_version_sorting(testing_workdir, testing_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(packages='impyla', repo='pypi', config=testing_config)
    m = api.render('impyla')[0][0]
    assert parse_version(m.version()) >= parse_version("0.13.8")


def test_list_skeletons():
    skeletons = api.list_skeletons()
    assert set(skeletons) == set(['pypi', 'cran', 'cpan', 'luarocks', 'rpm'])


@pytest.mark.serial
def test_pypi_with_entry_points(testing_workdir):
    api.skeletonize('planemo', repo='pypi', python_version="2.7")
    assert os.path.isdir('planemo')


@pytest.mark.serial
def test_pypi_with_version_arg(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/1442
    api.skeletonize('PrettyTable', 'pypi', version='0.7.2')
    m = api.render('prettytable')[0][0]
    assert parse_version(m.version()) == parse_version("0.7.2")


@pytest.mark.serial
def test_pypi_with_extra_specs(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/1697
    api.skeletonize('bigfile', 'pypi', extra_specs=["cython", "mpi4py"], version='0.1.24')
    m = api.render('bigfile')[0][0]
    assert parse_version(m.version()) == parse_version("0.1.24")
    assert any('cython' in req for req in m.meta['requirements']['build'])
    assert any('mpi4py' in req for req in m.meta['requirements']['build'])


@pytest.mark.serial
def test_pypi_with_version_inconsistency(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/189
    api.skeletonize('mpi4py_test', 'pypi', extra_specs=["mpi4py"], version='0.0.10')
    m = api.render('mpi4py_test')[0][0]
    assert parse_version(m.version()) == parse_version("0.0.10")


@pytest.mark.serial
def test_pypi_with_basic_environment_markers(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/1974
    api.skeletonize('coconut', 'pypi', version='1.2.2')
    m = api.render('coconut')[0][0]

    build_reqs = str(m.meta['requirements']['build'])
    run_reqs = str(m.meta['requirements']['run'])
    # should include the right dependencies for the right version
    if sys.version_info < (3,):
        assert "futures" in build_reqs
        assert "futures" in run_reqs
    else:
        assert "futures" not in build_reqs
        assert "futures" not in run_reqs
    if sys.version_info >= (2, 7):
        assert "pygments" in build_reqs
        assert "pygments" in run_reqs
    else:
        assert "pygments" not in build_reqs
        assert "pygments" not in run_reqs


@pytest.mark.serial
def test_setuptools_test_requirements(testing_workdir):
    api.skeletonize(packages='hdf5storage', repo='pypi')
    m = api.render('hdf5storage')[0][0]
    assert m.meta['test']['requires'] == ['nose >=1.0']
