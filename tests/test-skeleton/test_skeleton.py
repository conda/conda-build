import os
import shutil
import subprocess
import tempfile

import pytest
import yaml

thisdir = os.path.dirname(os.path.realpath(__file__))


@pytest.fixture(scope="function")
def tmpdir(request):
    tmpdir=tempfile.mkdtemp()

    def fin():
        shutil.rmtree(tmpdir)
    request.addfinalizer(fin)
    return tmpdir


def test_skeleton_by_name(tmpdir):
    cmd = "conda skeleton pypi --output-dir {} conda".format(tmpdir)
    subprocess.check_call(cmd.split())


def test_name_with_version_specified(tmpdir):
    tmpdir=tempfile.mkdtemp()
    cmd = "conda skeleton pypi --output-dir {} --version=0.7.5 sympy".format(tmpdir)
    subprocess.check_call(cmd.split())
    with open('{}/sympy-0.7.5/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('{}/sympy/meta.yaml'.format(tmpdir)) as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)


def test_url(tmpdir):
    cmd = "conda skeleton pypi --output-dir {} \
https://pypi.io/packages/source/s/sympy/\
sympy-0.7.5.tar.gz#md5=7de1adb49972a15a3dd975e879a2bea9".format(tmpdir)
    subprocess.check_call(cmd.split())
    with open('{}/sympy-0.7.5-url/meta.yaml'.format(thisdir)) as f:
        expected = yaml.load(f)
    with open('{}/sympy/meta.yaml'.format(tmpdir)) as f:
        actual = yaml.load(f)
    assert expected == actual, (expected, actual)
