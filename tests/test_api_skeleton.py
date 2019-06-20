import os
import sys

from pkg_resources import parse_version
import pytest

try:
    import ruamel_yaml
except ImportError:
    try:
        import ruamel.yaml as ruamel_yaml
    except ImportError:
        raise ImportError("No ruamel_yaml library available.\n"
                          "To proceed, conda install ruamel_yaml")


from conda_build import api
from conda_build.exceptions import DependencyNeedsBuildingError
from conda_build.utils import on_win

thisdir = os.path.dirname(os.path.realpath(__file__))

repo_packages = [('', 'pypi', 'pip', '8.1.2'),
                 ('r', 'cran', 'acs', ''),
                 ('r', 'cran', 'https://github.com/twitter/AnomalyDetection.git', ''),
                 ('perl', 'cpan', 'Moo', ''),
                 ('', 'rpm', 'libX11-devel', ''),
                 # ('lua', luarocks', 'LuaSocket', ''),
                 ]


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


def test_name_with_version_specified(testing_workdir, testing_config):
    api.skeletonize(packages='sympy', repo='pypi', version='0.7.5', config=testing_config)
    m = api.render('sympy/meta.yaml')[0][0]
    assert m.version() == "0.7.5"


def test_pypi_url(testing_workdir, testing_config):
    api.skeletonize('https://pypi.python.org/packages/source/s/sympy/'
                    'sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9',
                    repo='pypi', config=testing_config)
    m = api.render('sympy/meta.yaml')[0][0]
    assert m.version() == "0.7.5"


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


def test_pypi_pin_numpy(testing_workdir, testing_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(packages='msumastro', repo='pypi', version='0.9.0', config=testing_config,
                    pin_numpy=True)
    with open(os.path.join('msumastro', 'meta.yaml')) as f:
        assert f.read().count('numpy x.x') == 2
    with pytest.raises(DependencyNeedsBuildingError):
        api.build('msumastro')


def test_pypi_version_sorting(testing_workdir, testing_config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(packages='impyla', repo='pypi', config=testing_config)
    m = api.render('impyla')[0][0]
    assert parse_version(m.version()) >= parse_version("0.13.8")


def test_list_skeletons():
    skeletons = api.list_skeletons()
    assert set(skeletons) == set(['pypi', 'cran', 'cpan', 'luarocks', 'rpm'])


def test_pypi_with_entry_points(testing_workdir):
    api.skeletonize('planemo', repo='pypi', python_version="2.7")
    assert os.path.isdir('planemo')


def test_pypi_with_version_arg(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/1442
    api.skeletonize('PrettyTable', 'pypi', version='0.7.2')
    m = api.render('prettytable')[0][0]
    assert parse_version(m.version()) == parse_version("0.7.2")


def test_pypi_with_extra_specs(testing_workdir, testing_config):
    # regression test for https://github.com/conda/conda-build/issues/1697
    # For mpi4py:
    testing_config.channel_urls.append('https://repo.anaconda.com/pkgs/free')
    extra_specs = ['cython', 'mpi4py']
    if not on_win:
        extra_specs.append('nomkl')
    api.skeletonize('bigfile', 'pypi', extra_specs=extra_specs,
                    version='0.1.24', python="3.6", config=testing_config)
    m = api.render('bigfile')[0][0]
    assert parse_version(m.version()) == parse_version("0.1.24")
    assert any('cython' in req for req in m.meta['requirements']['host'])
    assert any('mpi4py' in req for req in m.meta['requirements']['host'])


def test_pypi_with_version_inconsistency(testing_workdir, testing_config):
    # regression test for https://github.com/conda/conda-build/issues/189
    # For mpi4py:
    extra_specs = ['mpi4py']
    if not on_win:
        extra_specs.append('nomkl')
    testing_config.channel_urls.append('https://repo.anaconda.com/pkgs/free')
    api.skeletonize('mpi4py_test', 'pypi', extra_specs=extra_specs,
                    version='0.0.10', python="3.6", config=testing_config)
    m = api.render('mpi4py_test')[0][0]
    assert parse_version(m.version()) == parse_version("0.0.10")


def test_pypi_with_basic_environment_markers(testing_workdir):
    # regression test for https://github.com/conda/conda-build/issues/1974
    api.skeletonize('coconut', 'pypi', version='1.2.2')
    m = api.render('coconut')[0][0]

    build_reqs = str(m.meta['requirements']['host'])
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


def test_setuptools_test_requirements(testing_workdir):
    api.skeletonize(packages='hdf5storage', repo='pypi')
    m = api.render('hdf5storage')[0][0]
    assert m.meta['test']['requires'] == ['nose >=1.0']


def test_pypi_section_order_preserved(testing_workdir):
    """
    Test whether sections have been written in the correct order.
    """
    from conda_build.render import FIELDS
    from conda_build.skeletons.pypi import (ABOUT_ORDER,
                                            REQUIREMENTS_ORDER,
                                            PYPI_META_STATIC)

    api.skeletonize(packages='sympy', repo='pypi')
    # Since we want to check the order of items in the recipe (not whether
    # the metadata values themselves are sensible), read the file as (ordered)
    # yaml, and check the order.
    with open('sympy/meta.yaml', 'r') as file:
        lines = [l for l in file.readlines() if not l.startswith("{%")]

    # The loader below preserves the order of entries...
    recipe = ruamel_yaml.load('\n'.join(lines), Loader=ruamel_yaml.RoundTripLoader)

    major_sections = list(recipe.keys())
    # Blank fields are omitted when skeletonizing, so prune any missing ones
    # before comparing.
    pruned_fields = [f for f in FIELDS if f in major_sections]
    assert major_sections == pruned_fields
    assert list(recipe['about']) == ABOUT_ORDER
    assert list(recipe['requirements']) == REQUIREMENTS_ORDER
    for k, v in PYPI_META_STATIC.items():
        assert list(v.keys()) == list(recipe[k])


# CRAN packages to test license_file entry.
# (package, license_id, license_family, license_file)
cran_packages = [('r-usethis', 'GPL-3', 'GPL3', 'GPL-3'),
                 ('r-abf2', 'Artistic-2.0', 'OTHER', 'Artistic-2.0'),
                 ('r-cortools', 'Artistic License 2.0', 'OTHER', 'Artistic-2.0'),
                 ('r-udpipe', 'MPL-2.0', 'OTHER', ''),
                 ]


@pytest.mark.parametrize("package, license_id, license_family, license_file", cran_packages)
def test_cran_license(package, license_id, license_family, license_file, testing_workdir, testing_config):
    api.skeletonize(packages=package, repo='cran', output_dir=testing_workdir,
                    config=testing_config)
    m = api.render(os.path.join(package, 'meta.yaml'))[0][0]
    m_license_id = m.get_value('about/license')
    assert m_license_id == license_id
    m_license_family = m.get_value('about/license_family')
    assert m_license_family == license_family
    m_license_file = m.get_value('about/license_file', '')
    assert os.path.basename(m_license_file) == license_file
