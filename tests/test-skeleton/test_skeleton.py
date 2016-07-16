import os
import shutil
import subprocess
import tempfile

import pytest
import yaml

thisdir = os.path.dirname(os.path.realpath(__file__))


@pytest.fixture(scope="function")
def tmpdir(request):
    tmpdir = tempfile.mkdtemp()

    def fin():
        shutil.rmtree(tmpdir)
    request.addfinalizer(fin)
    return tmpdir


def test_skeleton_by_name(tmpdir):
    cmd = "conda skeleton pypi --output-dir {} pip".format(tmpdir)
    subprocess.check_call(cmd.split())


def test_name_with_version_specified(tmpdir):
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


def test_skeleton_with_setup_options(tmpdir):
    # Use package below because  skeleton will fail unless the setup.py is given
    # the flag --offline because of a bootstrapping a helper file that
    # occurs by default.

    # Test that the setup option is used in constructing the skeleton.
    cmd = ("conda skeleton pypi --output-dir {} --version=0.2.2 photutils "
           "--setup-options=--offline".format(tmpdir))
    subprocess.check_call(cmd.split())

    # Check that the setup option occurs in bld.bat and build.sh.
    for script in ['bld.bat', 'build.sh']:
        with open('{}/ccdproc/{}'.format(tmpdir, script)) as f:
            content = f.read()
            assert '--offline' in content


def test_skeleton_pin_numpy(tmpdir):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    cmd = "conda skeleton pypi --output-dir {} --version=0.9.0 --pin-numpy msumastro".format(tmpdir)
    subprocess.check_call(cmd.split())

    with open('{}/msumastro/meta.yaml'.format(tmpdir)) as f:
        actual = yaml.load(f)

    assert 'numpy x.x' in actual['requirements']['run']
    assert 'numpy x.x' in actual['requirements']['build']
