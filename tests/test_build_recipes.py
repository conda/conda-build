import os
import subprocess
import shutil
import sys
import tarfile
import tempfile

from conda.compat import PY3
from conda.fetch import download
from conda.config import subdir
import pytest

from conda.compat import PY3, TemporaryDirectory
from conda.config import subdir
from conda.fetch import download

from conda_build.source import _guess_patch_strip_level, apply_patch
import conda_build.config as config

# noqa is because flake8 does not understand how testing_workdir works as a fixture
from .utils import metadata_dir, is_valid_dir, fail_dir, testing_workdir  # noqa

# Used for translating local paths into url (file://) paths
#   http://stackoverflow.com/a/14298190/1170370
def path2url(path):
    return urlparse.urljoin('file:', urllib.pathname2url(path))

@pytest.fixture(params=[dirname for dirname in os.listdir(metadata_dir)
                        if is_valid_dir(metadata_dir, dirname)])
def recipe(request):
    return os.path.join(metadata_dir, request.param)


def test_recipe_builds(recipe, testing_workdir):
    env = dict(os.environ)
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    env["CONDA_TEST_VAR"] = "conda_test"
    env["CONDA_TEST_VAR_2"] = "conda_test_2"

    cmd = 'conda build --no-anaconda-upload {}'.format(recipe)

    # allow the recipe to customize its build
    driver = os.path.join(recipe, '_driver.sh')
    if os.access(driver, os.X_OK):
        cmd = "{} {}".format(driver, cmd)
    subprocess.check_call(cmd.split(), env=env)



# def test_skip_existing_anaconda_org():
#     """This test may give false errors, because multiple tests running in parallel (on different
#     platforms) will all use the same central anaconda.org account.  Thus, this test is only reliable
#     if it is being run by one person on one machine at a time."""
#     # generated with conda_test_account user, command:
#     #    anaconda auth --create --name CONDA_BUILD_UPLOAD_TEST --scopes 'api repos conda'
#     token = "co-79de533f-926f-4e5e-a766-d393e33ae98f"
#     cmd = 'conda build --token {} {}'.format(token, os.path.join(metadata_dir, "empty_sections"))
#     subprocess.check_call(cmd.split())

#     try:
#         # ensure that we skip with the package in the anaconda.org channel
#         cmd = ('conda build --no-anaconda-upload --override-channels '
#                '-c conda_test_account --skip-existing {}'
#                 .format(os.path.join(metadata_dir, "empty_sections")))
#         process = subprocess.Popen(cmd.split(),
#                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#         output, error = process.communicate()
#         output = output.decode('utf-8')
#         error = error.decode('utf-8')
#     except:
#         raise
#     finally:
#         # clean up: remove the package
#         cmd = 'anaconda --token {} remove --force conda_test_account/empty_sections'\
#             .format(token)
#         subprocess.check_call(cmd.split())

#     assert "is already built" in output, error
#     assert "conda_test_account" in output, error


