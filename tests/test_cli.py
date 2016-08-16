# For the most part, all functionality should be tested with the api tests,
#   because they actually provide coverage.  These tests are here to make
#   sure that the CLI still works.

import json
import os
import subprocess
import sys

import pytest

from conda_build.conda_interface import PY3, download

from conda_build.utils import get_site_packages
from .utils import testing_workdir, metadata_dir, subdir, package_has_file, testing_env


def test_build():
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(metadata_dir, "python_run"))
    subprocess.check_call(cmd.split(), env=os.environ.copy())


def test_build_add_channel():
    """This recipe requires the blinker package, which is only on conda-forge.
    This verifies that the -c argument works."""
    cmd = ('conda build --no-anaconda-upload '
           '-c conda_build_test {}'.format(os.path.join(metadata_dir,
                                                   "_recipe_requiring_external_channel")))
    subprocess.check_call(cmd.split())


@pytest.mark.xfail
def test_build_without_channel_fails():
    cmd = ('conda --build --no-anaconda-upload {}'.format(os.path.join(metadata_dir,
                                                   "_recipe_requiring_external_channel")))
    # remove the conda forge channel from the arguments and make sure that we fail.  If we don't,
    #    we probably have channels in condarc, and this is not a good test.
    subprocess.check_call(cmd.split())


def test_render_output_build_path():
    cmd = 'conda render --output {0}'.format(
        os.path.join(metadata_dir, "python_run"),
        sys.version_info.major, sys.version_info.minor)
    process = subprocess.Popen(cmd.split(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=os.environ.copy())
    output, error = process.communicate()
    test_path = "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor)
    if PY3:
        output = output.decode("UTF-8")
        error = error.decode("UTF-8")
    assert os.path.basename(output.rstrip()) == test_path, error


def test_render_output_build_path_set_python():
    # build the other major thing, whatever it is
    if sys.version_info.major == 3:
        version = "2.7"
    else:
        version = "3.5"

    cmd = 'conda render --output {0} --python {1}'.format(
        os.path.join(metadata_dir, "python_run"), version)
    process = subprocess.Popen(cmd.split(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=os.environ.copy())
    output, error = process.communicate()
    test_path = "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      version.split('.')[0], version.split('.')[1])
    if PY3:
        output = output.decode("UTF-8")
        error = error.decode("UTF-8")
    assert os.path.basename(output.rstrip()) == test_path, error


def test_build_output_build_path():
    cmd = 'conda build --output {0}'.format(
        os.path.join(metadata_dir, "python_run"),
        sys.version_info.major, sys.version_info.minor)
    process = subprocess.Popen(cmd.split(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy())
    output, error = process.communicate()
    test_path = os.path.join(sys.prefix, "conda-bld", subdir,
                                  "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    if PY3:
        output = output.decode("UTF-8")
        error = error.decode("UTF-8")
    assert output.rstrip() == test_path, error


def test_skeleton_pypi(testing_workdir):
    subprocess.check_call('conda skeleton pypi click'.split(), env=os.environ.copy())
    assert os.path.isdir('click')
    # ensure that recipe generated is buildable
    subprocess.check_call('conda build click --no-anaconda-upload'.split(), env=os.environ.copy())


def test_metapackage(testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    subprocess.check_call(('conda metapackage metapackage_test 1.0 '
                           '-d bzip2 '
                           ).split(), env=os.environ.copy())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-0.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_build_number(testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    subprocess.check_call(('conda metapackage metapackage_test 1.0 '
                           '-d bzip2 '
                           '--build-number 1 '
                           ).split(), env=os.environ.copy())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-1.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_build_string(testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    subprocess.check_call(('conda metapackage metapackage_test 1.0 '
                           '-d bzip2 '
                           '--build-string frank '
                           ).split(), env=os.environ.copy())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-frank.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_metadata(testing_workdir):
    subprocess.check_call(("conda metapackage metapackage_test 1.0 "
                           "-d bzip2 "
                           "--home http://abc.com "
                           "--summary wee "
                           "--license BSD"
                           ).split(), env=os.environ.copy())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-0.tar.bz2')
    assert os.path.isfile(test_path)
    info = json.loads(package_has_file(test_path, 'info/index.json').decode('utf-8'))
    assert info['license'] == 'BSD'
    info = json.loads(package_has_file(test_path, 'info/about.json').decode('utf-8'))
    assert info['home'] == 'http://abc.com'
    assert info['summary'] == 'wee'


def test_index(testing_workdir):
    subprocess.check_call("conda index .".split(), env=os.environ.copy())
    assert os.path.isfile('repodata.json')


def test_inspect_installable(testing_workdir):
    subprocess.check_call(("conda inspect channels --test-installable conda-team").split(),
                          env=os.environ.copy())


def test_inspect_linkages(testing_workdir):
    # get a package that has known object output
    if sys.platform == 'win32':
        with pytest.raises(subprocess.CalledProcessError) as exc:
            out = subprocess.check_output(("conda inspect linkages python").split(), env=os.environ.copy())
            assert 'conda inspect linkages is only implemented in Linux and OS X' in exc
    else:
        out = subprocess.check_output(("conda inspect linkages python").split(), env=os.environ.copy())
        if PY3:
            out = out.decode('utf-8')
        assert 'openssl' in out


def test_inspect_objects(testing_workdir):
    # get a package that has known object output
    if sys.platform != 'darwin':
        with pytest.raises(subprocess.CalledProcessError) as exc:
            out = subprocess.check_output(("conda inspect objects python").split(), env=os.environ.copy())
            assert 'conda inspect objects is only implemented in OS X' in exc
    else:
        out = subprocess.check_output(("conda inspect objects python").split(), env=os.environ.copy())
        if PY3:
            out = out.decode('utf-8')
        assert 'rpath: @loader_path' in out


def test_develop(testing_env):
    f = "https://pypi.io/packages/source/c/conda_version_test/conda_version_test-0.1.0-1.tar.gz"
    download(f, "conda_version_test.tar.gz")
    from conda_build.utils import tar_xf
    tar_xf("conda_version_test.tar.gz", testing_env)
    extract_folder = 'conda_version_test-0.1.0-1'
    cwd = os.getcwd()
    subprocess.check_output('conda develop -p {0} {1}'.format(testing_env, extract_folder).split(),
                            env=os.environ.copy())
    assert cwd in open(os.path.join(get_site_packages(testing_env), 'conda.pth')).read()
    subprocess.check_output('conda develop --uninstall -p {0} {1}'.format(testing_env,
                                                                          extract_folder).split(),
                            env=os.environ.copy())
    assert (cwd not in open(os.path.join(get_site_packages(testing_env), 'conda.pth')).read())


def test_convert(testing_workdir):
    # download a sample py2.7 package
    f = 'https://repo.continuum.io/pkgs/free/win-64/affine-2.0.0-py27_0.tar.bz2'
    pkg_name = "affine-2.0.0-py27_0.tar.bz2"
    download(f, pkg_name)
    # convert it to all platforms
    subprocess.check_call('conda convert -o converted --platform all {0}'.format(pkg_name).split(),
                          env=os.environ.copy())
    platforms = ['osx-64', 'win-32', 'win-64', 'linux-64', 'linux-32']
    for platform in platforms:
        assert os.path.isdir(os.path.join('converted', platform))
        assert pkg_name in os.listdir(os.path.join('converted', platform))


def test_sign(testing_workdir):
    # test keygen
    subprocess.check_call('conda sign -k testkey'.split(), env=os.environ.copy())
    keypath = os.path.expanduser("~/.conda/keys/testkey")
    assert os.path.isfile(keypath)
    assert os.path.isfile(keypath + '.pub')

    # test signing
    # download a test package
    f = 'https://repo.continuum.io/pkgs/free/win-64/affine-2.0.0-py27_0.tar.bz2'
    pkg_name = "affine-2.0.0-py27_0.tar.bz2"
    download(f, pkg_name)
    subprocess.check_call('conda sign {0}'.format(pkg_name).split(), env=os.environ.copy())
    assert os.path.isfile(pkg_name + '.sig')

    # test verification
    subprocess.check_call('conda sign -v {0}'.format(pkg_name).split(), env=os.environ.copy())
    os.remove(keypath)
    os.remove(keypath + '.pub')
