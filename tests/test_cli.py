# For the most part, all functionality should be tested with the api tests,
#   because they actually provide coverage.  These tests are here to make
#   sure that the CLI still works.

import json
import os
import sys

import pytest

from conda_build.conda_interface import download

from conda_build.utils import get_site_packages
from .utils import testing_workdir, metadata_dir, package_has_file, testing_env, test_config

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
    args = ['--no-anaconda-upload', os.path.join(metadata_dir, "python_run")]
    main_build.execute(args)


def test_build_add_channel():
    """This recipe requires the blinker package, which is only on conda-forge.
    This verifies that the -c argument works."""

    args = ['--no-anaconda-upload', '-c', 'conda_build_test',
            os.path.join(metadata_dir, "_recipe_requiring_external_channel")]
    main_build.execute(args)


@pytest.mark.xfail
def test_build_without_channel_fails(testing_workdir):
    # remove the conda forge channel from the arguments and make sure that we fail.  If we don't,
    #    we probably have channels in condarc, and this is not a good test.
    args = ['--no-anaconda-upload',
            os.path.join(metadata_dir, "_recipe_requiring_external_channel")]
    main_build.execute(args)


def test_render_output_build_path(testing_workdir, capfd):
    args = ['--output', os.path.join(metadata_dir, "python_run")]
    main_render.execute(args)
    test_path = "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor)
    output, error = capfd.readouterr()
    assert os.path.basename(output.rstrip()) == test_path, error


def test_build_output_build_path(testing_workdir, test_config, capfd):
    args = ['--output', os.path.join(metadata_dir, "python_run")]
    main_render.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                                  "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    output, error = capfd.readouterr()
    assert output.rstrip() == test_path, error


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


def test_skeleton_pypi(testing_workdir):
    args = ['pypi', 'click']
    main_skeleton.execute(args)
    assert os.path.isdir('click')

    # ensure that recipe generated is buildable
    args = ['click', '--no-anaconda-upload']
    main_build.execute(args)


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
        assert os.path.isdir(os.path.join('converted', platform))
        assert pkg_name in os.listdir(os.path.join('converted', platform))


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
