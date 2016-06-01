import os
import subprocess
import shutil
import sys
import tempfile

import pytest

from conda.compat import PY3, TemporaryDirectory
from conda.config import subdir
from conda.fetch import download

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, "test-recipes/metadata")
fail_dir = os.path.join(thisdir, "test-recipes/fail")


def is_valid_dir(parent_dir, dirname):
    valid = os.path.isdir(os.path.join(parent_dir, dirname))
    valid &= not dirname.startswith("_")
    valid &= ('osx_is_app' != dirname or sys.platform == "darwin")
    return valid


# TODO: this does not currently take into account post-build versioning changes with __conda_? files
def test_output_build_path_git_source():
    cmd = 'conda build --output {}'.format(os.path.join(metadata_dir, "source_git_jinja2"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    test_path = os.path.join(sys.prefix, "conda-bld", subdir,
                        "conda-build-test-source-git-jinja2-1.8.1-py{}{}_0_gf3d51ae.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    if PY3:
        output = output.decode("UTF-8")
    assert output.rstrip() == test_path


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows permission errors w/ git when removing repo files on cleanup.")
def test_cached_source_not_interfere_with_versioning():
    """Test that work dir does not cache and cause inaccurate test target"""
    basedir = os.getcwd()
    try:
        with TemporaryDirectory() as tmp:
            os.chdir(tmp)
            subprocess.check_call(['git', 'clone',
                                   'https://github.com/conda/conda_build_test_recipe'])
            # build to make sure we have a work directory with source in it.
            #    We want to make sure that whatever version that is does not
            #    interfere with the test we run next.
            subprocess.check_call(['conda', 'build', '--no-test',
                                '--no-anaconda-upload',
                                'conda_build_test_recipe'])

            os.chdir('conda_build_test_recipe')
            subprocess.check_call(['git', 'checkout', '1.20.0'])
            os.chdir('..')

            # this should fail, because we have not built v1.0, so there should
            # be nothing to test.  If it succeeds, it means that it used the
            # cached master checkout for determining which version to test.
            cmd = 'conda build --output conda_build_test_recipe'
            output = subprocess.check_output(cmd.split())
            if PY3:
                output = output.decode("UTF-8")
            assert ("conda-build-test-source-git-jinja2-1.20.0" in output)
    finally:
        os.chdir(basedir)


def test_package_test():
    """Test calling conda build -t <package file> - rather than <recipe dir>"""
    filename = "jinja2-2.8-py{}{}_0.tar.bz2".format(sys.version_info.major, sys.version_info.minor)
    downloaded_file = os.path.join(sys.prefix, 'conda-bld', subdir, filename)
    if not os.path.isfile(downloaded_file):
        download('https://anaconda.org/conda-forge/jinja2/2.8/download/{}/{}'.format(subdir, filename),  # noqa
                 downloaded_file)
    subprocess.check_call(["conda", "build", "--test", downloaded_file])


@pytest.fixture(params=[dirname for dirname in os.listdir(metadata_dir)
                        if is_valid_dir(metadata_dir, dirname)])
def recipe(request):
    cwd = os.getcwd()
    os.chdir(metadata_dir)

    def fin():
        os.chdir(cwd)
    request.addfinalizer(fin)
    return os.path.join(metadata_dir, request.param)


def test_recipe_builds(recipe):
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


def test_dirty_variable_available_in_build_scripts():
    cmd = 'conda build --no-anaconda-upload --dirty {}'.format(os.path.join(metadata_dir,
                                                                    "_dirty_skip_section"))
    subprocess.check_call(cmd.split())
    with pytest.raises(subprocess.CalledProcessError):
        cmd = cmd.replace(" --dirty", "")
        subprocess.check_call(cmd.split())


def test_checkout_tool_as_dependency():
    # "hide" svn by putting a known bad one on PATH
    tmpdir = tempfile.mkdtemp()
    dummyfile = os.path.join(tmpdir, "svn")
    # empty prefix by default - extra bit at beginning of file
    prefix = ""
    if sys.platform != "win32":
        prefix = "#!/bin/bash\nexec 1>&2\n"
    with open(dummyfile, 'w') as f:
        f.write(prefix + """
echo
echo " ******* You've reached the dummy svn. It's likely there's a bug in conda  *******"
echo " ******* that makes it not add the _build/bin directory onto the PATH      *******"
echo " ******* before running the source checkout tool                           *******"
echo
exit -1
""")
    if sys.platform == "win32":
        os.rename(dummyfile, dummyfile + ".bat")
    else:
        import stat
        st = os.stat(dummyfile)
        os.chmod(dummyfile, st.st_mode | stat.S_IEXEC)
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([tmpdir, env["PATH"]])
    cmd = 'conda build --no-anaconda-upload {}/_checkout_tool_as_dependency'.format(metadata_dir)
    try:
        subprocess.check_call(cmd.split(), env=env)
    except subprocess.CalledProcessError:
        raise
    finally:
        shutil.rmtree(tmpdir)


platforms = ["64" if sys.maxsize > 2**32 else "32"]
if sys.platform == "win32":
    platforms = set(["32", ] + platforms)
    compilers = ["2.7", "3.4", "3.5"]
else:
    compilers = [".".join([str(sys.version_info.major), str(sys.version_info.minor)])]


@pytest.mark.parametrize("platform", platforms)
@pytest.mark.parametrize("target_compiler", compilers)
def test_cmake_generator(platform, target_compiler):
    # TODO: need a better way to specify compiler more directly on win
    cmd = 'conda build --no-anaconda-upload {}/_cmake_generator --python={}'.\
          format(metadata_dir, target_compiler)
    subprocess.check_call(cmd.split())


@pytest.mark.skipif(sys.platform == "win32",
                    reason="No windows symlinks")
def test_symlink_fail():
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(fail_dir, "symlinks"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    error = error.decode('utf-8')
    assert error.count("Error") == 6


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows doesn't show this error")
def test_broken_conda_meta():
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(fail_dir, "conda-meta"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    error = error.decode('utf-8')
    assert "Error: Untracked file(s) ('conda-meta/nope',)" in error


def test_recursive_fail():
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(fail_dir, "recursive-build"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    error = error.decode('utf-8')
    assert "recursive-build2" in error


def test_jinja_typo():
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(fail_dir,
                                                                    "source_git_jinja2_oops"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    error = error.decode('utf-8')
    assert "'GIT_DSECRIBE_TAG' is undefined" in error


def test_skip_existing():
    # build the recipe first
    cmd = 'conda build --no-anaconda-upload {}'.format(os.path.join(metadata_dir, "build_number"))
    subprocess.check_call(cmd.split())
    cmd = 'conda build --no-anaconda-upload --skip-existing {}'.format(os.path.join(metadata_dir,
                                                                                    "build_number"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, _ = process.communicate()
    output = output.decode('utf-8')
    assert "is already built, skipping." in output


def test_token_upload():
    # generated with conda_test_account user, command:
    #    anaconda auth --create --name CONDA_BUILD_UPLOAD_TEST --scopes 'api repos conda'
    token = "co-79de533f-926f-4e5e-a766-d393e33ae98f"
    # the folder with the test recipe to upload
    cmd = 'conda build --token {} {}'.format(token, os.path.join(metadata_dir, "empty_sections"))
    subprocess.check_call(cmd.split())
    # clean up - we don't actually want this package to exist
    cmd = 'anaconda --token {} remove --force conda_test_account/conda-build-test-empty_sections'\
    .format(token)
    subprocess.check_call(cmd.split())
