"""
This module tests the build API.  These are high-level integration tests.
"""

from collections import OrderedDict
import logging
import os
import subprocess
import sys
import tarfile

from conda_build.conda_interface import PY3, url_path, load_condarc, sys_rc_path

from binstar_client.commands import remove, show
from binstar_client.errors import NotFound
import pytest
import yaml

from conda_build import api
from conda_build.utils import copy_into, on_win

from .utils import (metadata_dir, fail_dir, is_valid_dir, testing_workdir, test_config)

# define a few commonly used recipes - use os.path.join(metadata_dir, recipe) elsewhere
empty_sections = os.path.join(metadata_dir, "empty_sections")


def represent_ordereddict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)


yaml.add_representer(OrderedDict, represent_ordereddict)


class AnacondaClientArgs(object):
    def __init__(self, specs, token=None, site=None, log_level=logging.INFO, force=False):
        from binstar_client.utils import parse_specs
        self.specs = [parse_specs(specs)]
        self.spec = self.specs[0]
        self.token = token
        self.site = site
        self.log_level = log_level
        self.force = force


def describe_root(cwd=None):
    if not cwd:
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tag = subprocess.check_output(["git", "describe", "--abbrev=0"], cwd=cwd).rstrip()
    if PY3:
        tag = tag.decode("utf-8")
    return tag


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
        api.test(recipe, config=test_config)


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
    output, error = capfd.readouterr()
    assert "Automatic uploading is disabled" in output, error


def test_git_describe_info_on_branch(test_config):
    output = api.get_output_file_path(os.path.join(metadata_dir, "_git_describe_number_branch"))
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                             "git_describe_number_branch-1.20.2-1_g82c6ba6.tar.bz2")
    assert test_path == output


def test_no_include_recipe_cmd_line_arg(test_config):
    """Two ways to not include recipe: build/include_recipe: False in meta.yaml; or this.
    Former is tested with specific recipe."""
    output_file = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                               "empty_sections-0.0-0.tar.bz2")
    api.build(empty_sections, anaconda_upload=False)
    assert package_has_file(output_file, "info/recipe/meta.yaml")

    # make sure that it is not there when the command line flag is passed
    api.build(empty_sections, anaconda_upload=False, include_recipe=False)
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_no_include_recipe_meta_yaml(test_config):
    # first, make sure that the recipe is there by default.  This test copied from above, but copied
    # as a sanity check here.
    output_file = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                               "empty_sections-0.0-0.tar.bz2")
    api.build(empty_sections, anaconda_upload=False)
    assert package_has_file(output_file, "info/recipe/meta.yaml")

    output_file = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                               "no_include_recipe-0.0-0.tar.bz2")
    api.build(os.path.join(metadata_dir, '_no_include_recipe'), anaconda_upload=False)
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_early_abort(capfd):
    """There have been some problems with conda-build dropping out early.
    Make sure we aren't causing them"""
    api.build(os.path.join(metadata_dir, '_test_early_abort'), anaconda_upload=False)
    output, error = capfd.readouterr()
    assert "Hello World" in output


def test_output_build_path_git_source(testing_workdir, test_config):
    output = api.get_output_file_path(os.path.join(metadata_dir, "source_git_jinja2"),
                                      config=test_config)
    test_path = os.path.join(test_config.croot, test_config.subdir,
                     "conda-build-test-source-git-jinja2-1.20.2-py{}{}_0_g262d444.tar.bz2".format(
                                      sys.version_info.major, sys.version_info.minor))
    assert output == test_path


def test_build_with_no_activate_does_not_activate():
    api.build(os.path.join(metadata_dir, '_set_env_var_no_activate_build'), activate=False)

@pytest.mark.skipif(sys.platform == "win32",
                    reason="no binary prefix manipulation done on windows.")
def test_binary_has_prefix_files(testing_workdir, test_config):
    api.build(os.path.join(metadata_dir, '_binary_has_prefix_files'), config=test_config)


def test_relative_path_git_versioning(testing_workdir, test_config):
    # conda_build_test_recipe is a manual step.  Clone it at the same level as
    #    your conda-build source.
    cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                       'conda_build_test_recipe'))
    tag = describe_root(cwd)
    recipe = os.path.join(metadata_dir, "_source_git_jinja2_relative_path")
    output = api.get_output_file_path(recipe, config=test_config)
    assert tag in output


def test_relative_git_url_git_versioning(testing_workdir, test_config):
    cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                       'conda_build_test_recipe'))
    tag = describe_root(cwd)
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
    # temporarily necessary because we have custom rebuilt svn for longer prefix here
    test_config.channel_urls = ('conda_build_test', )
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
    # verify that the correct compiler is available
    cl_versions = {"9.0": 15,
                   "10.0": 16,
                   "11.0": 17,
                   "12.0": 18,
                   "14.0": 19}

    os.environ['CONDATEST_MSVC_VER'] = msvc_ver
    os.environ['CL_EXE_VERSION'] = str(cl_versions[msvc_ver])

    try:
        # Always build Python 2.7 - but set MSVC version manually via Jinja template
        api.build(os.path.join(metadata_dir, '_build_msvc_compiler'), python="2.7")
    except:
        raise
    finally:
        del os.environ['CONDATEST_MSVC_VER']
        del os.environ['CL_EXE_VERSION']


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
    assert error.count("Error") == 6, "did not find appropriate count of Error in: " + error


def test_pip_in_meta_yaml_fail(testing_workdir, test_config):
    with pytest.raises(RuntimeError) as exc:
        api.build(os.path.join(fail_dir, "pip_reqs_fail_informatively"), config=test_config)
        assert "Received dictionary as spec." in str(exc)

@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows doesn't show this error")
def test_broken_conda_meta(testing_workdir, test_config):
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(fail_dir, "conda-meta"), config=test_config)
        assert "Error: Untracked file(s) ('conda-meta/nope',)" in str(exc)


def test_recursive_fail(testing_workdir, test_config):
    with pytest.raises(RuntimeError) as exc:
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

def test_skip_existing_url(testing_workdir, test_config, capfd):
    # make sure that it is built
    api.build(empty_sections, config=test_config)
    output_file = os.path.join(test_config.croot, test_config.subdir, "empty_sections-0.0-0.tar.bz2")

    platform = os.path.join(testing_workdir, test_config.subdir)
    copy_into(output_file, os.path.join(platform, os.path.basename(output_file)))

    # create the index so conda can find the file
    api.update_index(platform, config=test_config)

    api.build(os.path.join(metadata_dir, "empty_sections"), skip_existing=True,
              config=test_config, channel_urls=[url_path(testing_workdir)])

    output, error = capfd.readouterr()
    assert "is already built" in output
    assert url_path(test_config.croot) in output


def test_failed_tests_exit_build(testing_workdir, test_config):
    """https://github.com/conda/conda-build/issues/1112"""
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(metadata_dir, "_test_failed_test_exits"), config=test_config)
        assert 'TESTS FAILED' in exc


def test_requirements_txt_for_run_reqs(testing_workdir, test_config):
    """
    If run reqs are blank, then conda-build looks for requirements.txt in the recipe folder.
    There has been a report of issue with unsatisfiable requirements at

    https://github.com/Anaconda-Platform/anaconda-server/issues/2565

    This test attempts to reproduce those conditions: a channel other than defaults with this
    requirements.txt
    """
    test_config.channel_urls = ('conda_build_test', )
    api.build(os.path.join(metadata_dir, "_requirements_txt_run_reqs"), config=test_config)


def test_compileall_compiles_all_good_files(testing_workdir, test_config):
    output_file = os.path.join(test_config.croot, test_config.subdir,
                               'test_compileall-1.0-py{0}{1}_0.tar.bz2'.format(
                                   sys.version_info.major, sys.version_info.minor))
    api.build(os.path.join(metadata_dir, "_compile-test"), config=test_config)
    good_files = ['f1.py', 'f3.py']
    bad_file = 'f2_bad.py'
    for f in good_files:
        assert package_has_file(output_file, f)
        # look for the compiled file also
        assert package_has_file(output_file, f + 'c')
    assert package_has_file(output_file, bad_file)
    assert not package_has_file(output_file, bad_file + 'c')


def test_render_setup_py_old_funcname(testing_workdir, test_config, caplog):
    logging.basicConfig(level=logging.INFO)
    api.build(os.path.join(metadata_dir, "_source_setuptools"), config=test_config)
    assert "Deprecation notice: the load_setuptools function has been renamed to " in caplog.text()


def test_condarc_channel_available(testing_workdir, test_config):
    rcfile = os.path.join(testing_workdir, ".condarc")
    # ensure that the test fails without the channel
    with open(rcfile, 'w') as f:
        f.write("channels:\n")
        f.write("  - defaults\n")
    load_condarc(rcfile)
    with pytest.raises(RuntimeError):
        api.build("{}/_condarc_channel".format(metadata_dir), config=test_config)

    with open(rcfile, 'w') as f:
        f.write("channels:\n")
        f.write("  - conda_build_test\n")
        f.write("  - defaults\n")
    load_condarc(rcfile)
    api.build("{}/_condarc_channel".format(metadata_dir), config=test_config)

    # clean up - remove this rcfile and go back to the system default rcfile
    load_condarc(sys_rc_path)


def test_debug_build_option(testing_workdir, test_config, caplog, capfd):
    logging.basicConfig(level=logging.INFO)
    info_message = "Starting new HTTPS connection"
    debug_message = "GET /pkgs/free/noarch/repodata.json.bz2 HTTP/1.1"
    api.build(os.path.join(metadata_dir, "jinja2"), config=test_config)
    # this comes from an info message
    assert info_message not in caplog.text()
    # this comes from a debug message
    assert debug_message not in caplog.text()

    api.build(os.path.join(metadata_dir, "jinja2"), config=test_config, debug=True)
    # this comes from an info message
    assert info_message in caplog.text()
    # this comes from a debug message
    assert debug_message in caplog.text()


@pytest.mark.skipif(on_win, reason="fortran compilers on win are hard.")
def test_numpy_setup_py_data(test_config):
    recipe_path = os.path.join(metadata_dir, '_numpy_setup_py_data')
    assert os.path.basename(api.get_output_file_path(recipe_path,
                            config=test_config, numpy="1.11")) == \
                            "load_setup_py_test-1.0a1-np111py{0}{1}_1.tar.bz2".format(
                                sys.version_info.major, sys.version_info.minor)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows permission errors w/ git when removing repo files on cleanup.")
def test_relative_git_url_submodule_clone(testing_workdir):
    """Test git submodules identified with relative URLs can be mirrored then cloned. Also tests
       pushing changes and new tags and making sure those are reflected with GIT_DESCRIBE_TAG"""
    toplevel = os.path.join(testing_workdir, 'toplevel')
    os.mkdir(toplevel)
    relative_sub = os.path.join(testing_workdir, 'relative_sub')
    os.mkdir(relative_sub)
    absolute_sub = os.path.join(testing_workdir, 'absolute_sub')
    os.mkdir(absolute_sub)

    git_env = os.environ
    git_env['GIT_AUTHOR_NAME'] = 'conda-build'
    git_env['GIT_COMMITTER_NAME'] = 'conda-build'
    git_env['GIT_COMMITTER_EMAIL'] = 'conda@conda-build.org'

    for tag in range(2):
        os.chdir(absolute_sub)
        if tag == 0:
            subprocess.check_call(['git', 'init'], env=git_env)
        with open('absolute', 'w') as f:
            f.write(str(tag))
        subprocess.check_call(['git', 'add', 'absolute'], env=git_env)
        subprocess.check_call(['git', 'commit', '-m', 'absolute {}'.format(tag)],
                                env=git_env)

        os.chdir(relative_sub)
        if tag == 0:
            subprocess.check_call(['git', 'init'])
        with open('relative', 'w') as f:
            f.write(str(tag))
        subprocess.check_call(['git', 'add', 'relative'], env=git_env)
        subprocess.check_call(['git', 'commit', '-m', 'relative {}'.format(tag)],
                                env=git_env)

        os.chdir(toplevel)
        if tag == 0:
            subprocess.check_call(['git', 'init'], env=git_env)
        with open('toplevel', 'w') as f:
            f.write(str(tag))
        subprocess.check_call(['git', 'add', 'toplevel'], env=git_env)
        subprocess.check_call(['git', 'commit', '-m', 'toplevel {}'.format(tag)],
                                env=git_env)
        if tag == 0:
            subprocess.check_call(['git', 'submodule', 'add', absolute_sub, 'absolute'],
                                    env=git_env)
            subprocess.check_call(['git', 'submodule', 'add',
                                    os.path.join('..', 'relative_sub'), 'relative'],
                                    env=git_env)
        subprocess.check_call(['git', 'tag', '-a', str(tag), '-m', 'tag {}'.format(tag)],
                                env=git_env)

        filename = os.path.join(testing_workdir, 'meta.yaml')
        data = OrderedDict([
            ('package', OrderedDict([
                ('name', 'relative_submodules'),
                ('version', '{{ GIT_DESCRIBE_TAG }}')])),
            ('source', OrderedDict([
                ('git_url', toplevel),
                ('git_tag', str(tag))]))
        ])

        with open(filename, 'w') as outfile:
            outfile.write(yaml.dump(data, default_flow_style=False))
        output = api.get_output_file_path(testing_workdir)
        assert ("relative_submodules-{}-0".format(tag) in output)
