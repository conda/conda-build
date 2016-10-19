"""
This module tests the build API.  These are high-level integration tests.
"""

from collections import OrderedDict
import logging
import os
import subprocess
import sys
import json
import uuid

# for version
import conda
from conda_build.conda_interface import PY3, url_path

from binstar_client.commands import remove, show
from binstar_client.errors import NotFound
import pytest
import yaml
import tarfile

from conda_build import api, exceptions, __version__
from conda_build.build import VersionOrder
from conda_build.utils import (copy_into, on_win, check_call_env, convert_path_for_cygwin_or_msys2,
                               package_has_file)
from conda_build.os_utils.external import find_executable

from .utils import (metadata_dir, fail_dir, is_valid_dir, testing_workdir, test_config,
                    add_mangling, test_metadata)

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


@pytest.fixture(params=[dirname for dirname in os.listdir(metadata_dir)
                        if is_valid_dir(metadata_dir, dirname)])
def recipe(request):
    return os.path.join(metadata_dir, request.param)


# This tests any of the folders in the test-recipes/metadata folder that don't start with _
def test_recipe_builds(recipe, test_config, testing_workdir):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    os.environ["CONDA_TEST_VAR"] = "conda_test"
    os.environ["CONDA_TEST_VAR_2"] = "conda_test_2"
    ok_to_test = api.build(recipe, config=test_config)
    if ok_to_test:
        api.test(recipe, config=test_config)


def test_token_upload(testing_workdir):
    folder_uuid = uuid.uuid4().hex
    # generated with conda_test_account user, command:
    #    anaconda auth --create --name CONDA_BUILD_UPLOAD_TEST --scopes 'api repos conda'
    args = AnacondaClientArgs(specs="conda_test_account/empty_sections_" + folder_uuid,
                              token="co-79de533f-926f-4e5e-a766-d393e33ae98f",
                              force=True)

    with pytest.raises(NotFound):
        show.main(args)

    metadata, _, _ = api.render(empty_sections, activate=False)
    metadata.meta['package']['name'] = '_'.join([metadata.name(), folder_uuid])
    metadata.config.token = args.token

    # the folder with the test recipe to upload
    api.build(metadata)

    # make sure that the package is available (should raise if it doesn't)
    show.main(args)

    # clean up - we don't actually want this package to exist
    remove.main(args)

    # verify cleanup:
    with pytest.raises(NotFound):
        show.main(args)


@pytest.mark.parametrize("service_name", ["binstar", "anaconda"])
def test_no_anaconda_upload_condarc(service_name, testing_workdir, test_config, capfd):
    api.build(empty_sections, config=test_config)
    output, error = capfd.readouterr()
    assert "Automatic uploading is disabled" in output, error


def test_git_describe_info_on_branch(test_config):
    output = api.get_output_file_path(os.path.join(metadata_dir, "_git_describe_number_branch"))
    test_path = os.path.join(sys.prefix, "conda-bld", test_config.subdir,
                             "git_describe_number_branch-1.20.2-1_g82c6ba6.tar.bz2")
    assert test_path == output


def test_no_include_recipe_config_arg(test_metadata):
    """Two ways to not include recipe: build/include_recipe: False in meta.yaml; or this.
    Former is tested with specific recipe."""
    output_file = api.get_output_file_path(test_metadata)
    api.build(test_metadata)
    assert package_has_file(output_file, "info/recipe/meta.yaml")

    # make sure that it is not there when the command line flag is passed
    test_metadata.config.include_recipe = False
    test_metadata.meta['build_number'] = 2
    output_file = api.get_output_file_path(test_metadata)
    api.build(test_metadata)
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_no_include_recipe_meta_yaml(test_metadata, test_config):
    # first, make sure that the recipe is there by default.  This test copied from above, but copied
    # as a sanity check here.
    output_file = api.get_output_file_path(test_metadata)
    api.build(test_metadata)
    assert package_has_file(output_file, "info/recipe/meta.yaml")

    output_file = api.get_output_file_path(os.path.join(metadata_dir, '_no_include_recipe'),
                                           config=test_config)
    api.build(os.path.join(metadata_dir, '_no_include_recipe'), config=test_config)
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_early_abort(test_config, capfd):
    """There have been some problems with conda-build dropping out early.
    Make sure we aren't causing them"""
    api.build(os.path.join(metadata_dir, '_test_early_abort'), config=test_config)
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


def test_build_with_activate_does_activate():
    api.build(os.path.join(metadata_dir, '_set_env_var_activate_build'), activate=True)


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


def dummy_executable(folder, exename):
    # empty prefix by default - extra bit at beginning of file
    if sys.platform == "win32":
        exename = exename + ".bat"
    dummyfile = os.path.join(folder, exename)
    if sys.platform == "win32":
        prefix = "@echo off\n"
    else:
        prefix = "#!/bin/bash\nexec 1>&2\n"
    with open(dummyfile, 'w') as f:
        f.write(prefix + """
    echo ******* You have reached the dummy {}. It is likely there is a bug in
    echo ******* conda that makes it not add the _build/bin directory onto the
    echo ******* PATH before running the source checkout tool
    exit -1
    """.format(exename))
    if sys.platform != "win32":
        import stat
        st = os.stat(dummyfile)
        os.chmod(dummyfile, st.st_mode | stat.S_IEXEC)
    return exename


def test_checkout_tool_as_dependency(testing_workdir, test_config):
    # temporarily necessary because we have custom rebuilt svn for longer prefix here
    test_config.channel_urls = ('conda_build_test', )
    # "hide" svn by putting a known bad one on PATH
    exename = dummy_executable(testing_workdir, "svn")
    old_path = os.environ["PATH"]
    os.environ["PATH"] = os.pathsep.join([testing_workdir, os.environ["PATH"]])
    FNULL = open(os.devnull, 'w')
    with pytest.raises(subprocess.CalledProcessError, message="Dummy svn was not executed"):
        check_call_env([exename, '--version'], stderr=FNULL)
    FNULL.close()
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

def test_skip_existing_url(test_metadata, testing_workdir, capfd):
    # make sure that it is built
    output_file = api.get_output_file_path(test_metadata)
    api.build(test_metadata)

    # Copy our package into some new folder
    platform = os.path.join(testing_workdir, test_metadata.config.subdir)
    copy_into(output_file, os.path.join(platform, os.path.basename(output_file)))

    # create the index so conda can find the file
    api.update_index(platform, config=test_metadata.config)

    test_metadata.config.skip_existing = True
    test_metadata.config.channel_urls = [url_path(testing_workdir)]
    api.build(test_metadata)

    output, error = capfd.readouterr()
    assert "is already built" in output
    assert url_path(test_metadata.config.croot) in output


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
        assert package_has_file(output_file, add_mangling(f))
    assert package_has_file(output_file, bad_file)
    assert not package_has_file(output_file, add_mangling(bad_file))


def test_render_setup_py_old_funcname(testing_workdir, test_config, caplog):
    logging.basicConfig(level=logging.INFO)
    api.build(os.path.join(metadata_dir, "_source_setuptools"), config=test_config)
    assert "Deprecation notice: the load_setuptools function has been renamed to " in caplog.text()


def test_debug_build_option(test_metadata, caplog, capfd):
    logging.basicConfig(level=logging.INFO)
    info_message = "Starting new HTTPS connection"
    debug_message = "GET /pkgs/free/noarch/repodata.json.bz2 HTTP/1.1"
    api.build(test_metadata)
    # this comes from an info message
    assert info_message not in caplog.text()
    # this comes from a debug message
    assert debug_message not in caplog.text()

    test_metadata.config.debug = True
    api.build(test_metadata)
    # this comes from an info message
    assert info_message in caplog.text()
    # this comes from a debug message
    assert debug_message in caplog.text()


@pytest.mark.skipif(not on_win, reason="only Windows is insane enough to have backslashes in paths")
def test_backslash_in_always_include_files_path(test_config):
    api.build(os.path.join(metadata_dir, '_backslash_in_include_files'))
    with pytest.raises(RuntimeError):
        api.build(os.path.join(fail_dir, 'backslash_in_include_files'))


def test_build_metadata_object(test_metadata):
    api.build(test_metadata)


@pytest.mark.skipif(on_win, reason="fortran compilers on win are hard.")
def test_numpy_setup_py_data(test_config):
    recipe_path = os.path.join(metadata_dir, '_numpy_setup_py_data')
    assert os.path.basename(api.get_output_file_path(recipe_path,
                            config=test_config, numpy="1.11")) == \
                            "load_setup_py_test-1.0a1-np111py{0}{1}_1.tar.bz2".format(
                                sys.version_info.major, sys.version_info.minor)


def test_relative_git_url_submodule_clone(testing_workdir):
    """
    A multi-part test encompassing the following checks:

    1. That git submodules identified with both relative and absolute URLs can be mirrored
       and cloned.

    2. That changes pushed to the original repository are updated in the mirror and finally
       reflected in the package version and filename via `GIT_DESCRIBE_TAG`.

    3. That `source.py` is using `check_call_env` and `check_output_env` and that those
       functions are using tools from the build env.
    """
    toplevel = os.path.join(testing_workdir, 'toplevel')
    os.mkdir(toplevel)
    relative_sub = os.path.join(testing_workdir, 'relative_sub')
    os.mkdir(relative_sub)
    absolute_sub = os.path.join(testing_workdir, 'absolute_sub')
    os.mkdir(absolute_sub)

    sys_git_env = os.environ.copy()
    sys_git_env['GIT_AUTHOR_NAME'] = 'conda-build'
    sys_git_env['GIT_AUTHOR_EMAIL'] = 'conda@conda-build.org'
    sys_git_env['GIT_COMMITTER_NAME'] = 'conda-build'
    sys_git_env['GIT_COMMITTER_EMAIL'] = 'conda@conda-build.org'

    # Find the git executable before putting our dummy one on PATH.
    git = find_executable('git')

    # Put the broken git on os.environ["PATH"]
    exename = dummy_executable(testing_workdir, 'git')
    old_path = os.environ["PATH"]
    os.environ["PATH"] = os.pathsep.join([testing_workdir, os.environ["PATH"]])
    # .. and ensure it gets run (and fails).
    FNULL = open(os.devnull, 'w')
    # Strangely ..
    #   stderr=FNULL suppresses the output from echo on OS X whereas
    #   stdout=FNULL suppresses the output from echo on Windows
    with pytest.raises(subprocess.CalledProcessError, message="Dummy git was not executed"):
        check_call_env([exename, '--version'], stdout=FNULL, stderr=FNULL)
    FNULL.close()

    for tag in range(2):
        os.chdir(absolute_sub)
        if tag == 0:
            subprocess.check_call([git, 'init'], env=sys_git_env)
        with open('absolute', 'w') as f:
            f.write(str(tag))
        subprocess.check_call([git, 'add', 'absolute'], env=sys_git_env)
        subprocess.check_call([git, 'commit', '-m', 'absolute{}'.format(tag)],
                                env=sys_git_env)

        os.chdir(relative_sub)
        if tag == 0:
            subprocess.check_call([git, 'init'], env=sys_git_env)
        with open('relative', 'w') as f:
            f.write(str(tag))
        subprocess.check_call([git, 'add', 'relative'], env=sys_git_env)
        subprocess.check_call([git, 'commit', '-m', 'relative{}'.format(tag)],
                                env=sys_git_env)

        os.chdir(toplevel)
        if tag == 0:
            subprocess.check_call([git, 'init'], env=sys_git_env)
        with open('toplevel', 'w') as f:
            f.write(str(tag))
        subprocess.check_call([git, 'add', 'toplevel'], env=sys_git_env)
        subprocess.check_call([git, 'commit', '-m', 'toplevel{}'.format(tag)],
                                env=sys_git_env)
        if tag == 0:
            subprocess.check_call([git, 'submodule', 'add',
                                    convert_path_for_cygwin_or_msys2(git, absolute_sub), 'absolute'],
                                    env=sys_git_env)
            subprocess.check_call([git, 'submodule', 'add', '../relative_sub', 'relative'],
                                    env=sys_git_env)
        else:
            # Once we use a more recent Git for Windows than 2.6.4 on Windows or m2-git we
            # can change this to `git submodule update --recursive`.
            subprocess.check_call([git, 'submodule', 'foreach', git, 'pull'], env=sys_git_env)
        subprocess.check_call([git, 'commit', '-am', 'added submodules@{}'.format(tag)],
                              env=sys_git_env)
        subprocess.check_call([git, 'tag', '-a', str(tag), '-m', 'tag {}'.format(tag)],
                                env=sys_git_env)

        # It is possible to use `Git for Windows` here too, though you *must* not use a different
        # (type of) git than the one used above to add the absolute submodule, because .gitmodules
        # stores the absolute path and that is not interchangeable between MSYS2 and native Win32.
        #
        # Also, git is set to False here because it needs to be rebuilt with the longer prefix. As
        # things stand, my _b_env folder for this test contains more than 80 characters.
        requirements = ('requirements', OrderedDict([
                        ('build',
                         ['git            # [False]',
                          'm2-git         # [win]',
                          'm2-filesystem  # [win]'])]))

        filename = os.path.join(testing_workdir, 'meta.yaml')
        data = OrderedDict([
            ('package', OrderedDict([
                ('name', 'relative_submodules'),
                ('version', '{{ GIT_DESCRIBE_TAG }}')])),
            ('source', OrderedDict([
                ('git_url', toplevel),
                ('git_tag', str(tag))])),
             requirements,
            ('build', OrderedDict([
                ('script',
                 ['git submodule --quiet foreach git log -n 1 --pretty=format:%%s > %PREFIX%\\summaries.txt  # [win]',    # NOQA
                  'git submodule --quiet foreach git log -n 1 --pretty=format:%s > $PREFIX/summaries.txt   # [not win]']) # NOQA
            ])),
            ('test', OrderedDict([
                ('commands',
                 ['echo absolute{}relative{} > %PREFIX%\\expected_summaries.txt        # [win]'.format(tag, tag),
                  'fc.exe /W %PREFIX%\\expected_summaries.txt %PREFIX%\\summaries.txt  # [win]',
                  'echo absolute{}relative{} > $PREFIX/expected_summaries.txt          # [not win]'.format(tag, tag),
                  'diff -wuN ${PREFIX}/expected_summaries.txt ${PREFIX}/summaries.txt  # [not win]']),
            ]))
        ])

        with open(filename, 'w') as outfile:
            outfile.write(yaml.dump(data, default_flow_style=False, width=999999999))
        # Reset the path because our broken, dummy `git` would cause `render_recipe`
        # to fail, while no `git` will cause the build_dependencies to be installed.
        os.environ["PATH"] = old_path
        # This will (after one spin round the loop) install and run 'git' with the
        # build env prepended to os.environ[]
        output = api.get_output_file_path(testing_workdir)
        assert ("relative_submodules-{}-0".format(tag) in output)
        api.build(testing_workdir)


def test_noarch(testing_workdir):
    filename = os.path.join(testing_workdir, 'meta.yaml')
    for noarch in (False, True):
        data = OrderedDict([
            ('package', OrderedDict([
                ('name', 'test'),
                ('version', '0.0.0')])),
            ('build', OrderedDict([
                 ('noarch', str(noarch))]))
            ])
        with open(filename, 'w') as outfile:
            outfile.write(yaml.dump(data, default_flow_style=False, width=999999999))
        output = api.get_output_file_path(testing_workdir)
        assert ("noarch" in output or not noarch)
        assert ("noarch" not in output or noarch)


def test_disable_pip(test_config):
    recipe_path = os.path.join(metadata_dir, '_disable_pip')
    metadata, _, _ = api.render(recipe_path, config=test_config)

    metadata.meta['build']['script'] = 'python -c "import pip"'
    with pytest.raises(SystemExit):
        api.build(metadata)

    metadata.meta['build']['script'] = 'python -c "import setuptools"'
    with pytest.raises(SystemExit):
        api.build(metadata)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason="rpath fixup only done on Linux so far.")
def test_rpath_linux(test_config):
    api.build(os.path.join(metadata_dir, "_rpath"), config=test_config)


def test_noarch_none_value(testing_workdir, test_config):
    recipe = os.path.join(metadata_dir, "_noarch_none")
    with pytest.raises(exceptions.CondaBuildException):
        api.build(recipe, config=test_config)


def test_noarch_foo_value(test_config):
    recipe = os.path.join(metadata_dir, "noarch_foo")
    fn = api.get_output_file_path(recipe, test_config)
    api.build(recipe, config=test_config)
    metadata = json.loads(package_has_file(fn, 'info/index.json').decode())
    assert 'noarch' in metadata
    assert metadata['noarch'] == "foo"


def test_about_json_content(test_metadata):
    api.build(test_metadata)
    fn = api.get_output_file_path(test_metadata)
    about = json.loads(package_has_file(fn, 'info/about.json').decode())
    assert 'conda_version' in about and about['conda_version'] == conda.__version__
    assert 'conda_build_version' in about and about['conda_build_version'] == __version__
    assert 'channels' in about and about['channels']
    try:
        assert 'env_vars' in about and about['env_vars']
    except AssertionError:
        # new versions of conda support this, so we should raise errors.
        if VersionOrder(conda.__version__) >= VersionOrder('4.2.10'):
            raise
        else:
            pass

    assert 'root_pkgs' in about and about['root_pkgs']


@pytest.mark.xfail(reason="Conda can not yet install `noarch: python` packages")
def test_noarch_python_with_tests(test_config):
    recipe = os.path.join(metadata_dir, "_noarch_python_with_tests")
    api.build(recipe, config=test_config)


def test_noarch_python(test_config):
    recipe = os.path.join(metadata_dir, "_noarch_python")
    fn = api.get_output_file_path(recipe, config=test_config)
    api.build(recipe, config=test_config)
    assert package_has_file(fn, 'info/files') is not ''
    noarch = json.loads(package_has_file(fn, 'info/noarch.json').decode())
    assert 'entry_points' in noarch
    assert 'type' in noarch


def test_skip_compile_pyc(test_config):
    recipe = os.path.join(metadata_dir, "skip_compile_pyc")
    fn = api.get_output_file_path(recipe, config=test_config)
    api.build(recipe, config=test_config)
    tf = tarfile.open(fn)
    pyc_count = 0
    for f in tf.getmembers():
        filename = os.path.basename(f.name)
        _, ext = os.path.splitext(filename)
        basename = filename.split('.', 1)[0]
        if basename == 'skip_compile_pyc':
            assert not ext == '.pyc', "a skip_compile_pyc .pyc was compiled: {}".format(filename)
        if ext == '.pyc':
            assert basename == 'compile_pyc', "an unexpected .pyc was compiled: {}".format(filename)
            pyc_count = pyc_count + 1
    assert pyc_count == 2, "there should be 2 .pyc files, instead there were {}".format(pyc_count)


def test_fix_permissions(test_config):
    recipe = os.path.join(metadata_dir, "fix_permissions")
    fn = api.get_output_file_path(recipe, config=test_config)
    api.build(recipe, config=test_config)
    tf = tarfile.open(fn)
    for f in tf.getmembers():
        assert f.mode & 0o444 == 0o444, "tar member '{}' has invalid (read) mode".format(f.name)


@pytest.mark.skipif(not on_win, reason="windows-only functionality")
def test_script_win_creates_exe(test_config):
    recipe = os.path.join(metadata_dir, "_script_win_creates_exe")
    fn = api.get_output_file_path(recipe, config=test_config)
    api.build(recipe, config=test_config)
    assert package_has_file(fn, 'Scripts/test-script.exe')
    assert package_has_file(fn, 'Scripts/test-script-script.py')
