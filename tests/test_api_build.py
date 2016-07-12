import logging
import os
import subprocess
import sys
import tarfile

from conda.compat import PY3
import conda.config as cc
from binstar_client.commands import remove, show
from binstar_client.errors import NotFound
import pytest

if PY3:
    import urllib.parse as urlparse
    import urllib.request as urllib
else:
    import urlparse
    import urllib

from conda_build import api

from .utils import (metadata_dir, fail_dir, is_valid_dir,
                    testing_workdir, test_config, path2url)

# define a few commonly used recipes - use os.path.join(metadata_dir, recipe) elsewhere
empty_sections = os.path.join(metadata_dir, "empty_sections")


class AnacondaClientArgs(object):
    def __init__(self, specs, token=None, site=None, log_level=logging.INFO, force=False):
        from binstar_client.utils import parse_specs
        self.specs = [parse_specs(specs)]
        self.spec = self.specs[0]
        self.token = token
        self.site = site
        self.log_level = log_level
        self.force = force


def package_has_file(package_path, file_path):
    try:
        with tarfile.open(package_path) as t:
            try:
                t.getmember(file_path)
                return True
            except KeyError:
                return False
            except OSError as e:
                raise RuntimeError("Could not extract %s (%s)" % (package_path, e))
    except tarfile.ReadError:
        raise RuntimeError("Could not extract metadata from %s. "
                           "File probably corrupt." % package_path)


@pytest.fixture(params=[dirname for dirname in os.listdir(metadata_dir)
                        if is_valid_dir(metadata_dir, dirname)])
def recipe(request):
    return os.path.join(metadata_dir, request.param)


# This tests any of the folders in the test-recipes/metadata forlder that don't start with _
def test_recipe_builds(recipe, test_config, testing_workdir):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    os.environ["CONDA_TEST_VAR"] = "conda_test"
    os.environ["CONDA_TEST_VAR_2"] = "conda_test_2"
    ok_to_test = api.build(recipe, config=test_config)
    if ok_to_test:
        api.test(recipe, config=config)


def test_token_upload(testing_workdir):
    # generated with conda_test_account user, command:
    #    anaconda auth --create --name CONDA_BUILD_UPLOAD_TEST --scopes 'api repos conda'
    args = AnacondaClientArgs(specs="conda_test_account/empty_sections",
                              token="co-79de533f-926f-4e5e-a766-d393e33ae98f",
                              force=True)

    # clean up - we don't actually want this package to exist yet
    remove.main(args)

    with pytest.raises(NotFound):
        show.main(args)
    # the folder with the test recipe to upload
    api.build(empty_sections, token=args.token)

    # make sure that the package is available (should raise if it doesn't)
    show.main(args)

    # clean up - we don't actually want this package to exist
    remove.main(args)

    # verify cleanup:
    with pytest.raises(NotFound):
        show.main(args)


@pytest.mark.parametrize("service_name", ["binstar", "anaconda"])
def test_no_anaconda_upload_condarc(service_name, testing_workdir, capfd):
    api.build(empty_sections, anaconda_upload=False)
    output, err = capfd.readouterr()
    assert "Automatic uploading is disabled" in output, err


def test_git_describe_info_on_branch():
    output = api.get_output_file_path(os.path.join(metadata_dir, "_git_describe_number_branch"))
    test_path = os.path.join(sys.prefix, "conda-bld", cc.subdir,
                             "git_describe_number_branch-1.20.2-1_g82c6ba6.tar.bz2")
    assert test_path == output


def test_no_include_recipe_cmd_line_arg():
    """Two ways to not include recipe: build/include_recipe: False in meta.yaml; or this.
    Former is tested with specific recipe."""
    output_file = os.path.join(sys.prefix, "conda-bld", cc.subdir,
                               "empty_sections-0.0-0.tar.bz2")
    api.build(empty_sections, anaconda_upload=False)
    assert package_has_file(output_file, "info/recipe/meta.yaml")

    # make sure that it is not there when the command line flag is passed
    api.build(empty_sections, anaconda_upload=False, include_recipe=False)
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_no_include_recipe_meta_yaml():
    # first, make sure that the recipe is there by default.  This test copied from above, but copied
    # as a sanity check here.
    output_file = os.path.join(sys.prefix, "conda-bld", cc.subdir,
                               "empty_sections-0.0-0.tar.bz2")
    api.build(empty_sections, anaconda_upload=False)
    assert package_has_file(output_file, "info/recipe/meta.yaml")

    output_file = os.path.join(sys.prefix, "conda-bld", cc.subdir,
                               "no_include_recipe-0.0-0.tar.bz2")
    api.build(os.path.join(metadata_dir, '_no_include_recipe'), anaconda_upload=False)
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_early_abort(capfd):
    """There have been some problems with conda-build dropping out early.
    Make sure we aren't causing them"""
    api.build(os.path.join(metadata_dir, '_test_early_abort'), anaconda_upload=False)
    output, err = capfd.readouterr()
    assert "Hello World" in output

def test_output_build_path_git_source(testing_workdir):
    cmd = 'conda build --output {}'.format(os.path.join(metadata_dir, "source_git_jinja2"))
    process = subprocess.Popen(cmd.split(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    test_path = os.path.join(sys.prefix, "conda-bld", cc.subdir,
                        "conda-build-test-source-git-jinja2-1.8.1-py{}{}_0_gf3d51ae.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    if PY3:
        output = output.decode("UTF-8")
        error = error.decode("UTF-8")
    assert output.rstrip() == test_path, error


def test_build_with_no_activate_does_not_activate():
    api.build(os.path.join(metadata_dir, '_set_env_var_no_activate_build'), activate=False)

@pytest.mark.skipif(sys.platform == "win32",
                    reason="no binary prefix manipulation done on windows.")
def test_binary_has_prefix_files(testing_workdir, test_config):
    api.build(os.path.join(metadata_dir, '_binary_has_prefix_files'), config=test_config)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows permission errors w/ git when removing repo files on cleanup.")
def test_cached_source_not_interfere_with_versioning(testing_workdir, test_config):
    """Test that work dir does not cache and cause inaccurate test target"""
    try:
        subprocess.check_call(['git', 'clone',
                                'https://github.com/conda/conda_build_test_recipe'])
        # build to make sure we have a work directory with source in it.
        #    We want to make sure that whatever version that is does not
        #    interfere with the test we run next.
        api.build('conda_build_test_recipe', notest=True, config=test_config)
        os.chdir('conda_build_test_recipe')
        subprocess.check_call(['git', 'checkout', '1.20.0'])
        os.chdir('..')

        # this should fail, because we have not built v1.0, so there should
        # be nothing to test.  If it succeeds, it means that it used the
        # cached master checkout for determining which version to test.
        cmd = 'conda build --output conda_build_test_recipe'
        api.get_output_file_path('conda_build_test_recipe', config=test_config)
        assert "conda-build-test-source-git-jinja2-1.20.0" in output
    except:
        raise


def test_relative_path_git_versioning(testing_workdir, test_config):
    tag = subprocess.check_output(["git", "describe", "--abbrev=0"]).rstrip()
    recipe = os.path.join(metadata_dir, "_source_git_jinja2_relative_path")
    output = api.get_output_file_path(recipe, config=test_config)
    assert tag in output


def test_relative_git_url_git_versioning(testing_workdir, test_config):
    tag = subprocess.check_output(["git", "describe", "--abbrev=0"]).rstrip()
    recipe = os.path.join(metadata_dir, "_source_git_jinja2_relative_git_url")
    output = api.get_output_file_path(recipe, config=test_config)
    assert tag in output


def test_dirty_variable_available_in_build_scripts(testing_workdir, test_config):
    recipe = os.path.join(metadata_dir, "_dirty_skip_section")
    test_config.dirty = True
    api.build(recipe, config=test_config)

    with pytest.raises(SystemExit):
        test_config.dirty = False
        api.build(recipe, config=test_config)


def test_checkout_tool_as_dependency(testing_workdir, test_config):
    # "hide" svn by putting a known bad one on PATH
    dummyfile = os.path.join(testing_workdir, "svn")
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
    env["PATH"] = os.pathsep.join([testing_workdir, env["PATH"]])
    api.build(os.path.join(metadata_dir, '_checkout_tool_as_dependency'), config=test_config)


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
    api.build(os.path.join(metadata_dir, '_build_msvc_compiler'), python="2.7")


@pytest.mark.parametrize("platform", platforms)
@pytest.mark.parametrize("target_compiler", compilers)
def test_cmake_generator(platform, target_compiler, testing_workdir, test_config):
    test_config.python = target_compiler
    api.build(os.path.join(metadata_dir, '_cmake_generator'), config=test_config)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="No windows symlinks")
def test_symlink_fail(testing_workdir, test_config, capfd):
    with pytest.raises(SystemExit):
        api.build(os.path.join(fail_dir, "symlinks"), config=test_config)
    output, error = capfd.readouterr()
    assert error.count("Error") == 6


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows doesn't show this error")
def test_broken_conda_meta(testing_workdir, test_config):
    with pytest.raises(SystemExit):
        api.build(os.path.join(fail_dir, "conda-meta"), config=test_config)
        assert "Error: Untracked file(s) ('conda-meta/nope',)" in exc


def test_recursive_fail(testing_workdir, test_config):
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(fail_dir, "recursive-build"), config=test_config)
        assert "recursive-build2" in exc


def test_jinja_typo(testing_workdir, test_config):
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(fail_dir, "source_git_jinja2_oops"), config=test_config)
        assert "'GIT_DSECRIBE_TAG' is undefined" in exc


def test_skip_existing(testing_workdir, test_config, capfd):
    # build the recipe first
    api.build(empty_sections, config=test_config)
    api.build(empty_sections, config=test_config, skip_existing=True)
    output, error = capfd.readouterr()
    assert "is already built" in output

def test_skip_existing_url(testing_workdir, test_config):
    # make sure that it is built
    api.build(empty_sections, config=test_config)
    output_file = os.path.join(test_config.croot, cc.subdir, "empty_sections-0.0-0.tar.bz2")

    platform = os.path.join(testing_workdir, cc.subdir)
    shutil.copy2(output_file, os.path.join(platform, os.path.basename(output_file)))

    # create the index so conda can find the file
    api.update_index(platform)

    channel_url = path2url(testing_workdir)
    test_config.skip_existing = True
    test_config.override_channels = True
    test_config.channel_urls = (channel_url, )
    api.build(os.path.join(metadata_dir, "empty_sections"), skip_existing=True, config=test_config)

    output, error = capfd.readouterr()
    assert "is already built" in output
    assert "is already built" in output, (output + error)
    assert channel_url in output, (output + error)
