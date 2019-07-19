import os
import sys

from pkg_resources import parse_version
import pytest

from conda_build.skeletons.pypi import get_package_metadata, get_pkginfo, \
    get_entry_points, is_setuptools_enabled, convert_to_flat_list

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
                 (
                 'r', 'cran', 'https://github.com/twitter/AnomalyDetection.git',
                 ''),
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
        package_name = "-".join(
            [prefix, base_package]) if prefix else base_package
        contents = os.listdir(testing_workdir)
        assert len([content for content in contents
                    if content.startswith(package_name.lower()) and
                    os.path.isdir(os.path.join(testing_workdir, content))])
    except:
        print(os.listdir(testing_workdir))
        raise


def test_name_with_version_specified(testing_workdir, testing_config):
    api.skeletonize(packages='sympy', repo='pypi', version='0.7.5',
                    config=testing_config)
    m = api.render('sympy/meta.yaml')[0][0]
    assert m.version() == "0.7.5"


def test_pypi_url(testing_workdir, testing_config):
    api.skeletonize('https://pypi.python.org/packages/source/s/sympy/'
                    'sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9',
                    repo='pypi', config=testing_config)
    m = api.render('sympy/meta.yaml')[0][0]
    assert m.version() == "0.7.5"


@pytest.fixture
def url_pylint_package():
    return "https://pypi.python.org/packages/source/p/pylint/pylint-2.3.1.tar.gz#sha256=723e3db49555abaf9bf79dc474c6b9e2935ad82230b10c1138a71ea41ac0fff1"


@pytest.fixture
def mock_metada_pylint(url_pylint_package):
    import re

    version, hash_type, hash_value = re.findall(
        r"pylint-(.*).tar.gz#(.*)=(.*)$", url_pylint_package
    )[0]

    return {
        'run_depends': '',
        'build_depends': '',
        'entry_points': '',
        'test_commands': '',
        'tests_require': '',
        'version': 'UNKNOWN',
        'pypiurl': url_pylint_package,
        'filename': "black-{version}.tar.gz".format(version=version),
        'digest': [hash_type, hash_value],
        'import_tests': '',
        'summary': ''
    }


def test_get_entry_points(
        testing_workdir, testing_config, mock_metada_pylint, url_pylint_package
):
    pkginfo = get_pkginfo(url_pylint_package,
                          filename=mock_metada_pylint['filename'],
                          pypiurl=mock_metada_pylint['pypiurl'],
                          digest=mock_metada_pylint['digest'],
                          python_version="3.7",
                          extra_specs=[],
                          setup_options=[],
                          config=testing_config)

    assert get_entry_points(pkginfo) == {
        'entry_points': [
            'pylint = pylint:run_pylint',
            'epylint = pylint:run_epylint',
            'pyreverse = pylint:run_pyreverse',
            'symilar = pylint:run_symilar'
        ],
        'test_commands': [
            'pylint --help',
            'epylint --help',
            'pyreverse --help',
            'symilar --help'
        ],
    }


def test_convert_to_flat_list():
    assert convert_to_flat_list("STRING") == ["STRING"]
    assert convert_to_flat_list([["LIST1", "LIST2"]]) == ["LIST1", "LIST2"]


def test_is_setuptools_enabled():
    assert not is_setuptools_enabled({"entry_points": "STRING"})
    assert not is_setuptools_enabled({
        "entry_points": {
            "console_scripts": ["CONSOLE"],
            "gui_scripts": ["GUI"],
        }
    })

    assert is_setuptools_enabled({
        "entry_points": {
            "console_scripts": ["CONSOLE"],
            "gui_scripts": ["GUI"],
            "foo_scripts": ["SCRIPTS"],
        }
    })



def test_get_package_metadata(
        testing_workdir, testing_config, url_pylint_package, mock_metada_pylint
):
    get_package_metadata(
        url_pylint_package,
        mock_metada_pylint,
        {},
        ".",
        "3.7",
        False,
        False,
        [url_pylint_package],
        False,
        True,
        [],
        [],
        config=testing_config,
        setup_options=[],
    )
    assert mock_metada_pylint == {
        'run_depends': [
            'astroid >=2.2.0,<3', 'isort >=4.2.5,<5', 'mccabe >=0.6,<0.7'
        ],
        'build_depends': [
            'pip', 'astroid >=2.2.0,<3', 'isort >=4.2.5,<5', 'mccabe >=0.6,<0.7'
        ],
        'entry_points': [
            'pylint = pylint:run_pylint',
            'epylint = pylint:run_epylint',
            'pyreverse = pylint:run_pyreverse',
            'symilar = pylint:run_symilar'
        ],
        'test_commands': [
            'pylint --help',
            'epylint --help',
            'pyreverse --help',
            'symilar --help'
        ],
        'tests_require': ['pytest'],
        'version': '2.3.1',
        'pypiurl': url_pylint_package,
        'filename': 'black-2.3.1.tar.gz',
        'digest': [
            'sha256',
            '723e3db49555abaf9bf79dc474c6b9e2935ad82230b10c1138a71ea41ac0fff1'
        ],
        'import_tests': [
            'pylint',
            'pylint.checkers',
            'pylint.extensions',
            'pylint.pyreverse',
            'pylint.reporters',
            'pylint.reporters.ureports'
        ],
        'summary': 'python code static checker',
        'packagename': 'pylint',
        'home': 'https://github.com/PyCQA/pylint',
        'license': 'GNU General Public (GPL)',
        'license_family': 'LGPL'
    }


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
                 (
                 'r-cortools', 'Artistic License 2.0', 'OTHER', 'Artistic-2.0'),
                 ('r-udpipe', 'MPL-2.0', 'OTHER', ''),
                 ]


@pytest.mark.parametrize("package, license_id, license_family, license_file",
                         cran_packages)
def test_cran_license(package, license_id, license_family, license_file,
                      testing_workdir, testing_config):
    api.skeletonize(packages=package, repo='cran', output_dir=testing_workdir,
                    config=testing_config)
    m = api.render(os.path.join(package, 'meta.yaml'))[0][0]
    m_license_id = m.get_value('about/license')
    assert m_license_id == license_id
    m_license_family = m.get_value('about/license_family')
    assert m_license_family == license_family
    m_license_file = m.get_value('about/license_file', '')
    assert os.path.basename(m_license_file) == license_file
