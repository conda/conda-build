# For the most part, all functionality should be tested with the api tests,
#   because they actually provide coverage.  These tests are here to make
#   sure that the CLI still works.

import json
import os
import subprocess
import sys
import yaml

import pytest

from conda_build.conda_interface import download
from conda_build.tarcheck import TarCheck

from conda_build import api
from conda_build.utils import get_site_packages, on_win, get_build_folders, package_has_file
from .utils import (testing_workdir, metadata_dir, testing_env, test_config, test_metadata,
                    put_bad_conda_on_path)

import conda_build.cli.main_build as main_build
import conda_build.cli.main_sign as main_sign
import conda_build.cli.main_render as main_render
import conda_build.cli.main_convert as main_convert
import conda_build.cli.main_develop as main_develop
import conda_build.cli.main_metapackage as main_metapackage
import conda_build.cli.main_skeleton as main_skeleton
import conda_build.cli.main_inspect as main_inspect
import conda_build.cli.main_index as main_index


def test_build():
    args = ['--no-anaconda-upload', os.path.join(metadata_dir, "empty_sections"), '--no-activate']
    main_build.execute(args)


# regression test for https://github.com/conda/conda-build/issues/1450
def test_build_with_conda_not_on_path(testing_workdir):
    with put_bad_conda_on_path(testing_workdir):
        # using subprocess is not ideal, but it is the easiest way to ensure that PATH
        #    is altered the way we want here.
        subprocess.check_call('conda-build {0}'.format(os.path.join(metadata_dir, "python_run")),
                              env=os.environ, shell=True)

def test_build_add_channel():
    """This recipe requires the blinker package, which is only on conda-forge.
    This verifies that the -c argument works."""

    args = ['--no-anaconda-upload', '-c', 'conda_build_test', '--no-activate',
            os.path.join(metadata_dir, "_recipe_requiring_external_channel")]
    main_build.execute(args)


@pytest.mark.xfail
def test_build_without_channel_fails(testing_workdir):
    # remove the conda forge channel from the arguments and make sure that we fail.  If we don't,
    #    we probably have channels in condarc, and this is not a good test.
    args = ['--no-anaconda-upload', '--no-activate',
            os.path.join(metadata_dir, "_recipe_requiring_external_channel")]
    main_build.execute(args)


def test_render_output_build_path(testing_workdir, capfd):
    args = ['--output', os.path.join(metadata_dir, "python_run")]
    main_render.execute(args)
    test_path = "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor)
    output, error = capfd.readouterr()
    assert error == ""
    assert os.path.basename(output.rstrip()) == test_path, error


def test_build_output_build_path(testing_workdir, test_config, capfd):
    args = ['--output', os.path.join(metadata_dir, "python_run")]
    main_build.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                                  "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    output, error = capfd.readouterr()
    assert error == ""
    assert output.rstrip() == test_path, error


def test_build_output_build_path_multiple_recipes(testing_workdir, test_config, capfd):
    skip_recipe = os.path.join(metadata_dir, "build_skip")
    args = ['--output', os.path.join(metadata_dir, "python_run"), skip_recipe]

    main_build.execute(args)

    test_path = lambda pkg: os.path.join(sys.prefix, "conda-bld", test_config.subdir, pkg)
    test_paths = [test_path(
        "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
        sys.version_info.major, sys.version_info.minor)),
        "Skipped: {} defines build/skip for this "
        "configuration.".format(os.path.abspath(skip_recipe))]

    output, error = capfd.readouterr()
    assert error == ""
    assert output.rstrip().splitlines() == test_paths, error

def test_slash_in_recipe_arg_keeps_build_id(testing_workdir, test_config):
    recipe_path = os.path.join(metadata_dir, "has_prefix_files" + os.path.sep)
    fn = api.get_output_file_path(recipe_path, config=test_config)
    args = [os.path.join(metadata_dir, "has_prefix_files"), '--croot', test_config.croot]
    main_build.execute(args)
    fn = api.get_output_file_path(recipe_path,
                                  config=test_config)
    assert package_has_file(fn, 'info/has_prefix')
    data = package_has_file(fn, 'info/has_prefix')
    if hasattr(data, 'decode'):
        data = data.decode('UTF-8')
    assert 'has_prefix_files_1' in data


def test_build_no_build_id(testing_workdir, test_config, capfd):
    args = [os.path.join(metadata_dir, "has_prefix_files"), '--no-build-id',
            '--croot', test_config.croot, '--no-activate',]
    main_build.execute(args)
    fn = api.get_output_file_path(os.path.join(metadata_dir, "has_prefix_files"),
                                  config=test_config)
    assert package_has_file(fn, 'info/has_prefix')
    data = package_has_file(fn, 'info/has_prefix')
    if hasattr(data, 'decode'):
        data = data.decode('UTF-8')
    assert 'has_prefix_files_1' not in data


def test_render_output_build_path_set_python(testing_workdir, capfd):
    # build the other major thing, whatever it is
    if sys.version_info.major == 3:
        version = "2.7"
    else:
        version = "3.5"

    args = ['--output', os.path.join(metadata_dir, "python_run"), '--python', version]
    main_render.execute(args)
    test_path = "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      version.split('.')[0], version.split('.')[1])
    output, error = capfd.readouterr()
    assert os.path.basename(output.rstrip()) == test_path, error


def test_skeleton_pypi(testing_workdir, test_config):
    args = ['pypi', 'click']
    main_skeleton.execute(args)
    assert os.path.isdir('click')

    # ensure that recipe generated is buildable
    args = ['click', '--no-anaconda-upload', '--croot', test_config.croot, '--no-activate',]
    main_build.execute(args)


def test_skeleton_pypi_arguments_work(testing_workdir, test_config):
    """
    These checks whether skeleton executes without error when these
    options are specified on the command line AND whether the underlying
    functionality works as a regression test for:

    https://github.com/conda/conda-build/pull/1384
    """
    args = ['pypi', 'msumastro', '--pin-numpy']
    main_skeleton.execute(args)
    assert os.path.isdir('msumastro')

    # Deliberately bypass metadata reading in conda build to get as
    # close to the "ground truth" as possible.
    with open('msumastro/meta.yaml') as f:
        actual = yaml.load(f)

    assert 'numpy x.x' in actual['requirements']['run']
    assert 'numpy x.x' in actual['requirements']['build']

    args = ['pypi', 'photutils', '--version=0.2.2', '--setup-options=--offline']
    main_skeleton.execute(args)
    assert os.path.isdir('photutils')
    # Check that the setup option occurs in bld.bat and build.sh.
    for script in ['bld.bat', 'build.sh']:
        with open('photutils/{}'.format(script)) as f:
            content = f.read()
            assert '--offline' in content

    with open(os.path.join('photutils', 'meta.yaml')) as f:
        content = f.read()
        assert 'version: "0.2.2"' in content


def test_metapackage(test_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ['metapackage_test', '1.0', '-d', 'bzip2']
    main_metapackage.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir, 'metapackage_test-1.0-0.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_build_number(test_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ['metapackage_test', '1.0', '-d', 'bzip2', '--build-number', '1']
    main_metapackage.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir, 'metapackage_test-1.0-1.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_build_string(test_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ['metapackage_test', '1.0', '-d', 'bzip2', '--build-string', 'frank']
    main_metapackage.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir, 'metapackage_test-1.0-frank.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_metadata(test_config, testing_workdir):
    args = ['metapackage_test', '1.0', '-d', 'bzip2', "--home", "http://abc.com", "--summary", "wee",
            "--license", "BSD"]
    main_metapackage.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir, 'metapackage_test-1.0-0.tar.bz2')
    assert os.path.isfile(test_path)
    info = json.loads(package_has_file(test_path, 'info/index.json').decode('utf-8'))
    assert info['license'] == 'BSD'
    info = json.loads(package_has_file(test_path, 'info/about.json').decode('utf-8'))
    assert info['home'] == 'http://abc.com'
    assert info['summary'] == 'wee'


def test_index(testing_workdir):
    args = ['.']
    main_index.execute(args)
    assert os.path.isfile('repodata.json')


def test_inspect_installable(testing_workdir):
    args = ['channels', '--test-installable', 'conda-team']
    main_inspect.execute(args)


def test_inspect_linkages(testing_workdir, capfd):
    # get a package that has known object output
    args = ['linkages', 'python']
    if sys.platform == 'win32':
        with pytest.raises(SystemExit) as exc:
            main_inspect.execute(args)
            assert 'conda inspect linkages is only implemented in Linux and OS X' in exc
    else:
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert 'openssl' in output


def test_inspect_objects(testing_workdir, capfd):
    # get a package that has known object output
    args = ['objects', 'python']
    if sys.platform != 'darwin':
        with pytest.raises(SystemExit) as exc:
            main_inspect.execute(args)
            assert 'conda inspect objects is only implemented in OS X' in exc
    else:
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert 'rpath: @loader_path' in output


@pytest.mark.skipif(on_win, reason="Windows prefix length doesn't matter (yet?)")
def test_inspect_prefix_length(testing_workdir, capfd):
    from conda_build import api
    # build our own known-length package here
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    fn = api.get_output_file_path(recipe_path, config=config)
    if os.path.isfile(fn):
        os.remove(fn)
    config.prefix_length = 80
    api.build(recipe_path, config=config)

    args = ['prefix-lengths', fn]
    with pytest.raises(SystemExit):
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert 'Packages with binary prefixes shorter than' in output
        assert fn in output

    config.prefix_length = 255
    api.build(recipe_path, config=config)
    main_inspect.execute(args)
    output, error = capfd.readouterr()
    assert 'No packages found with binary prefixes shorter' in output


def test_develop(testing_env):
    f = "https://pypi.io/packages/source/c/conda_version_test/conda_version_test-0.1.0-1.tar.gz"
    download(f, "conda_version_test.tar.gz")
    from conda_build.utils import tar_xf
    tar_xf("conda_version_test.tar.gz", testing_env)
    extract_folder = 'conda_version_test-0.1.0-1'
    cwd = os.getcwd()
    args = ['-p', testing_env, extract_folder]
    main_develop.execute(args)
    assert cwd in open(os.path.join(get_site_packages(testing_env), 'conda.pth')).read()

    args = ['--uninstall', '-p', testing_env, extract_folder]
    main_develop.execute(args)
    assert (cwd not in open(os.path.join(get_site_packages(testing_env), 'conda.pth')).read())


def test_convert(testing_workdir):
    # download a sample py2.7 package
    f = 'https://repo.continuum.io/pkgs/free/win-64/affine-2.0.0-py27_0.tar.bz2'
    pkg_name = "affine-2.0.0-py27_0.tar.bz2"
    download(f, pkg_name)
    # convert it to all platforms
    args = ['-o', 'converted', '--platform', 'all', pkg_name]
    main_convert.execute(args)
    platforms = ['osx-64', 'win-32', 'win-64', 'linux-64', 'linux-32']
    for platform in platforms:
        dirname = os.path.join('converted', platform)
        assert os.path.isdir(dirname)
        assert pkg_name in os.listdir(dirname)
        with TarCheck(os.path.join(dirname, pkg_name)) as tar:
            tar.correct_subdir(platform)


def test_sign(testing_workdir):
    # test keygen
    args = ['-k', 'testkey']
    main_sign.execute(args)
    keypath = os.path.expanduser("~/.conda/keys/testkey")
    assert os.path.isfile(keypath)
    assert os.path.isfile(keypath + '.pub')

    # test signing
    # download a test package
    f = 'https://repo.continuum.io/pkgs/free/win-64/affine-2.0.0-py27_0.tar.bz2'
    pkg_name = "affine-2.0.0-py27_0.tar.bz2"
    download(f, pkg_name)
    args = [pkg_name]
    main_sign.execute(args)
    assert os.path.isfile(pkg_name + '.sig')

    # test verification
    args = ['-v', pkg_name]
    main_sign.execute(args)
    os.remove(keypath)
    os.remove(keypath + '.pub')


def test_purge(testing_workdir, test_metadata):
    """
    purge clears out build folders - things like some_pkg_12048309850135

    It does not clear out build packages from folders like osx-64 or linux-64.
    """
    api.build(test_metadata)
    fn = api.get_output_file_path(test_metadata)
    args = ['purge']
    main_build.execute(args)
    assert not get_build_folders(test_metadata.config.croot)
    assert os.path.isfile(fn)


def test_purge_all(test_metadata):
    """
    purge-all clears out build folders as well as build packages in the osx-64 folders and such
    """
    api.build(test_metadata)
    fn = api.get_output_file_path(test_metadata)
    args = ['purge-all', '--croot', test_metadata.config.croot]
    main_build.execute(args)
    assert not get_build_folders(test_metadata.config.croot)
    assert not os.path.isfile(fn)
