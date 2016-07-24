# For the most part, all functionality should be tested with the api tests,
#   because they actually provide coverage.  These tests are here to make
#   sure that the CLI still works.

import json
import os
import subprocess
import sys

import pytest

from conda.compat import PY3

from .utils import testing_workdir, metadata_dir, subdir, package_has_file


def test_build():
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(metadata_dir, "python_run"))
    subprocess.check_call(cmd.split())


def test_render_output_build_path():
    cmd = 'conda render --output {}'.format(os.path.join(metadata_dir, "python_run"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    test_path = os.path.join(sys.prefix, "conda-bld", subdir,
                                  "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    if PY3:
        output = output.decode("UTF-8")
        error = error.decode("UTF-8")
    assert output.rstrip() == test_path, error


def test_build_output_build_path():
    cmd = 'conda build --output {}'.format(os.path.join(metadata_dir, "python_run"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    test_path = os.path.join(sys.prefix, "conda-bld", subdir,
                                  "conda-build-test-python-run-1.0-py{}{}_0.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    if PY3:
        output = output.decode("UTF-8")
        error = error.decode("UTF-8")
    assert output.rstrip() == test_path, error


def test_skeleton_pypi(testing_workdir):
    subprocess.check_call('conda skeleton pypi click'.split())
    assert os.path.isdir('click')
    # ensure that recipe generated is buildable
    subprocess.check_call('conda build click --no-anaconda-upload'.split())


def test_metapackage(testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    subprocess.check_call(('conda metapackage metapackage_test 1.0 '
                           '-d bzip2 '
                           ).split())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-1.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_build_number(testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    subprocess.check_call(('conda metapackage metapackage_test 1.0 '
                           '-d bzip2 '
                           '--build-number 1 '
                           ).split())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-1.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_build_string(testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    subprocess.check_call(('conda metapackage metapackage_test 1.0 '
                           '-d bzip2 '
                           '--build-string frank '
                           ).split())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-frank.tar.bz2')
    assert os.path.isfile(test_path)


def test_metapackage_metadata(testing_workdir):
    subprocess.check_call(("conda metapackage metapackage_test 1.0 "
                           "-d bzip2 "
                           "--home http://abc.com "
                           "--summary wee "
                           "--license BSD"
                           ).split())
    test_path = os.path.join(sys.prefix, "conda-bld", subdir, 'metapackage_test-1.0-0.tar.bz2')
    assert os.path.isfile(test_path)
    info = json.loads(package_has_file(test_path, 'info/index.json'))
    assert info['license'] == 'BSD'
    info = json.loads(package_has_file(test_path, 'info/about.json'))
    assert info['home'] == 'http://abc.com'
    assert info['summary'] == 'wee'


def test_index(testing_workdir):
    subprocess.check_call("conda index .".split())
    assert os.path.isfile('repodata.json')


def test_inspect_installable(testing_workdir):
    subprocess.check_call(("conda inspect channels --test-installable conda-team").split())


def test_inspect_linkages(testing_workdir):
    # get a package that has known object output
    out = subprocess.check_output(("conda inspect linkages python").split())
    assert 'openssl' in out


@pytest.mark.skipif(sys.platform != 'darwin',
                    reason="Inspect objects only supported on Mac")
def test_inspect_objects(testing_workdir):
    # get a package that has known object output
    out = subprocess.check_output(("conda inspect objects python").split())
    assert 'rpath: @loader_path' in out


def test_develop(testing_workdir):
    raise NotImplementedError


def test_convert(testing_workdir):
    raise NotImplementedError


def test_sign(testing_workdir):
    raise NotImplementedError
