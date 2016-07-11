from contextlib import contextmanager
import os
import sys

import pytest

from conda.compat import StringIO

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, "test-recipes/metadata")
fail_dir = os.path.join(thisdir, "test-recipes/fail")


def is_valid_dir(parent_dir, dirname):
    valid = os.path.isdir(os.path.join(parent_dir, dirname))
    valid &= not dirname.startswith("_")
    valid &= ('osx_is_app' != dirname or sys.platform == "darwin")
    return valid


@pytest.fixture
def testing_workdir(tmpdir, request):
    """ Create a workdir in a safe temporary folder; cd into dir above before test, cd out after

    :param tmpdir: py.test fixture, will be injected
    :param request: py.test fixture-related, will be injected (see pytest docs)
    """

    saved_path = os.getcwd()

    tmpdir.chdir()
    workdir = tmpdir.mkdir('mysubdir')

    def return_to_saved_path():
        os.chdir(saved_path)

    request.addfinalizer(return_to_saved_path)

    return str(workdir)


@pytest.fixture
def test_config(testing_workdir, request):
    return Config(croot=testing_workdir)


#  <========== stolen from conda; included here because conda's test folder not installed with conda. ====>


expected_error_prefix = 'Using Anaconda Cloud api site https://api.anaconda.org'
def strip_expected(stderr):
    if expected_error_prefix and stderr.startswith(expected_error_prefix):
        stderr = stderr[len(expected_error_prefix):].lstrip()
    return stderr


class CapturedText(object):
    pass


@contextmanager
def captured(disallow_stderr=True):
    """
    Context manager to capture the printed output of the code in the with block

    Bind the context manager to a variable using `as` and the result will be
    in the stdout property.

    >>> from tests.helpers import captured
    >>> with captured() as c:
    ...     print('hello world!')
    ...
    >>> c.stdout
    'hello world!\n'
    """
    stdout = sys.stdout
    stderr = sys.stderr
    sys.stdout = outfile = StringIO()
    sys.stderr = errfile = StringIO()
    c = CapturedText()
    yield c
    c.stdout = outfile.getvalue()
    c.stderr = strip_expected(errfile.getvalue())
    sys.stdout = stdout
    sys.stderr = stderr
    if disallow_stderr and c.stderr:
        raise Exception("Got stderr output: %s" % c.stderr)
