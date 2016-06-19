import os
import subprocess
import shutil
import sys
import tempfile

import pytest

from conda.compat import PY3, TemporaryDirectory
from conda.config import subdir
from conda.fetch import download
from conda_build.source import _guess_patch_strip_level, apply_patch

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, 'test-recipes', 'metadata')
fail_dir = os.path.join(thisdir, 'test-recipes', 'fail')


def is_valid_dir(parent_dir, dirname):
    valid = os.path.isdir(os.path.join(parent_dir, dirname))
    valid &= not dirname.startswith("_")
    valid &= ('osx_is_app' != dirname or sys.platform == "darwin")
    return valid


# def test_CONDA_BLD_PATH():
#     env = dict(os.environ)
#     cmd = 'conda build --no-anaconda-upload {}/source_git_jinja2'.format(metadata_dir)
#     with TemporaryDirectory() as tmp:
#         env["CONDA_BLD_PATH"] = tmp
#         subprocess.check_call(cmd.split(), env=env)
#         # trick is actually a second pass, to make sure that deletion/trash moving is working OK.
#         subprocess.check_call(cmd.split(), env=env)


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
        error = error.decode("UTF-8")
    assert output.rstrip() == test_path, error


def test_build_in_activated_env_restores_activated_env():
    with TemporaryDirectory() as tmp:
        env = os.path.join(tmp, "env")
        subprocess.check_call('conda create -p {} python=2.7'.format(env).split())
        source = "source " if not sys.platform == 'win32' else ""
        echo_env = ("echo $CONDA_DEFAULT_ENV" if not sys.platform == 'win32' else
                    "set CONDA_DEFAULT_ENV")
        cmd = ("{source}activate {envdir} && "
               "conda build --no-anaconda-upload {recipe} && "
               "{echo}").format(source=source, envdir=env,
                                recipe=os.path.join(metadata_dir, "source_git_jinja2"),
                                echo=echo_env)
        shell = ["cmd.exe", "/d", "/c"] if sys.platform == 'win32' else ['bash', '-l', '-c']
        shell.append(cmd)
        process = subprocess.Popen(shell, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        output, error = process.communicate()
        if PY3:
            output = output.decode("UTF-8")
            error = error.decode("UTF-8")
        sys.stderr.write(output)
        sys.stderr.write(error)
        assert output.rstrip().endswith(env), error


def test_build_with_no_activate_does_not_activate():
    cmd = ('conda build --no-anaconda-upload --no-activate '
           '{}/_set_env_var_no_activate_build').format(metadata_dir)
    subprocess.check_call(cmd.split(), cwd=metadata_dir)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="no binary prefix manipulation done on windows.")
def test_binary_has_prefix_files():
    cmd = 'conda build --no-anaconda-upload {}/_binary_has_prefix_files'.format(metadata_dir)
    subprocess.check_call(cmd.split())


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
    except:
        raise
    finally:
        os.chdir(basedir)


def test_relative_path_git_versioning():
    tag = subprocess.check_output(["git", "describe", "--abbrev=0"]).rstrip()
    cmd = 'conda build --output {}'.format(os.path.join(metadata_dir,
                                                        "_source_git_jinja2_relative_path"))
    output = subprocess.check_output(cmd.split())
    assert tag in output


def test_relative_git_url_git_versioning():
    tag = subprocess.check_output(["git", "describe", "--abbrev=0"]).rstrip()
    cmd = 'conda build --output {}'.format(os.path.join(metadata_dir,
                                                        "_source_git_jinja2_relative_git_url"))
    output = subprocess.check_output(cmd.split())
    assert tag in output


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
    msvc_vers = ['9.0', '10.0', '14.0']
else:
    msvc_vers = []
    compilers = [".".join([str(sys.version_info.major), str(sys.version_info.minor)])]


@pytest.mark.skipif(sys.platform != "win32", reason="MSVC only on windows")
@pytest.mark.parametrize("msvc_ver", msvc_vers)
def test_build_msvc_compiler(msvc_ver):
    env = dict(os.environ)
    # verify that the correct compiler is available
    cl_versions = {"9.0": 15,
                   "10.0": 16,
                   "11.0": 17,
                   "12.0": 18,
                   "14.0": 19}

    env['CONDATEST_MSVC_VER'] = msvc_ver
    env['CL_EXE_VERSION'] = str(cl_versions[msvc_ver])

    # Always build Python 2.7 - but set MSVC version manually via Jinja template
    cmd = 'conda build {} --python=2.7 --no-anaconda-upload'.format(
        os.path.join(metadata_dir, '_build_msvc_compiler'))
    subprocess.check_call(cmd.split(), env=env)


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


@pytest.mark.parametrize("service_name", ["binstar", "anaconda"])
def test_no_anaconda_upload_condarc(service_name):
    with TemporaryDirectory() as tmp:
        rcfile = os.path.join(tmp, ".condarc")
        with open(rcfile, 'w') as f:
            f.write("{}_upload: False\n".format(service_name))
        env = os.environ.copy()
        env["CONDARC"] = rcfile
        cmd = "conda build {}/empty_sections".format(metadata_dir)
        process = subprocess.Popen(cmd.split(),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   env=env)
        output, error = process.communicate()
        output = output.decode('utf-8')
        error = error.decode('utf-8')
        sys.stderr.write(output)
        assert "Automatic uploading is disabled" in output, error


def test_patch_strip_level():
    patchfiles = set(('some/common/prefix/one.txt',
                      'some/common/prefix/two.txt',
                      'some/common/prefix/three.txt'))
    folders = ('some', 'common', 'prefix')
    files = ('one.txt', 'two.txt', 'three.txt')
    basedir = os.getcwd()
    with TemporaryDirectory() as tmp:
        os.chdir(tmp)
        os.makedirs(os.path.join(tmp, *folders))
        for file in files:
            with open(os.path.join(os.path.join(tmp, *folders), file), 'w') as f:
                f.write('hello\n')
        assert _guess_patch_strip_level(patchfiles, os.getcwd()) == 0
        os.chdir(folders[0])
        assert _guess_patch_strip_level(patchfiles, os.getcwd()) == 1
        os.chdir(folders[1])
        assert _guess_patch_strip_level(patchfiles, os.getcwd()) == 2
        os.chdir(folders[2])
        assert _guess_patch_strip_level(patchfiles, os.getcwd()) == 3
        os.chdir(basedir)


def test_patch():
    basedir = os.getcwd()
    with TemporaryDirectory() as tmp:
        os.chdir(tmp)
        with open(os.path.join(tmp, 'file-deletion.txt'), 'w') as f:
            f.write('hello\n')
        with open(os.path.join(tmp, 'file-modification.txt'), 'w') as f:
            f.write('hello\n')
        patchfile = os.path.join(tmp, 'patch')
        with open(patchfile, 'w') as f:
            f.write('diff file-deletion.txt file-deletion.txt\n')
            f.write('--- file-deletion.txt	2016-06-07 21:55:59.549798700 +0100\n')
            f.write('+++ file-deletion.txt	1970-01-01 01:00:00.000000000 +0100\n')
            f.write('@@ -1 +0,0 @@\n')
            f.write('-hello\n')
            f.write('diff file-creation.txt file-creation.txt\n')
            f.write('--- file-creation.txt	1970-01-01 01:00:00.000000000 +0100\n')
            f.write('+++ file-creation.txt	2016-06-07 21:55:59.549798700 +0100\n')
            f.write('@@ -0,0 +1 @@\n')
            f.write('+hello\n')
            f.write('diff file-modification.txt file-modification.txt.new\n')
            f.write('--- file-modification.txt	2016-06-08 18:23:08.384136600 +0100\n')
            f.write('+++ file-modification.txt.new	2016-06-08 18:23:37.565136200 +0100\n')
            f.write('@@ -1 +1 @@\n')
            f.write('-hello\n')
            f.write('+43770\n')
            f.close()
            apply_patch(tmp, patchfile)
            assert not os.path.exists(os.path.join(tmp, 'file-deletion.txt'))
            assert os.path.exists(os.path.join(tmp, 'file-creation.txt'))
            assert os.path.exists(os.path.join(tmp, 'file-modification.txt'))
            with open('file-modification.txt', 'r') as modified:
                lines = modified.readlines()
                assert lines[0] == '43770\n'
        os.chdir(basedir)
