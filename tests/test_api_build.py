"""
This module tests the build API.  These are high-level integration tests.
"""

from collections import OrderedDict
from glob import glob
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
from conda_build.render import finalize_metadata
from conda_build.utils import (copy_into, on_win, check_call_env, convert_path_for_cygwin_or_msys2,
                               package_has_file, check_output_env, conda_43)
from conda_build.os_utils.external import find_executable

from .utils import is_valid_dir, metadata_dir, fail_dir, add_mangling

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
    tag = check_output_env(["git", "describe", "--abbrev=0"], cwd=cwd).rstrip()
    if PY3:
        tag = tag.decode("utf-8")
    return tag


@pytest.fixture(params=[dirname for dirname in os.listdir(metadata_dir)
                        if is_valid_dir(metadata_dir, dirname)])
def recipe(request):
    return os.path.join(metadata_dir, request.param)


# This tests any of the folders in the test-recipes/metadata folder that don't start with _
def test_recipe_builds(recipe, testing_config, testing_workdir, monkeypatch):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    monkeypatch.setenv("CONDA_TEST_VAR", "conda_test")
    monkeypatch.setenv("CONDA_TEST_VAR_2", "conda_test_2")
    api.build(recipe, config=testing_config)


def test_token_upload(testing_workdir):
    folder_uuid = uuid.uuid4().hex
    # generated with conda_test_account user, command:
    #    anaconda auth --create --name CONDA_BUILD_UPLOAD_TEST --scopes 'api repos conda'
    args = AnacondaClientArgs(specs="conda_test_account/empty_sections_" + folder_uuid,
                              token="co-79de533f-926f-4e5e-a766-d393e33ae98f",
                              force=True)

    with pytest.raises(NotFound):
        show.main(args)

    metadata = api.render(empty_sections, activate=False)[0][0]
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
def test_no_anaconda_upload_condarc(service_name, testing_workdir, testing_config, capfd):
    api.build(empty_sections, config=testing_config)
    output, error = capfd.readouterr()
    assert "Automatic uploading is disabled" in output, error


def test_git_describe_info_on_branch(testing_config):
    recipe_path = os.path.join(metadata_dir, "_git_describe_number_branch")
    output = api.get_output_file_path(recipe_path)[0]
    _hash = api.render(recipe_path, config=testing_config)[0][0]._hash_dependencies()
    test_path = os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir,
                    "git_describe_number_branch-1.20.2.0-{}_1_g82c6ba6.tar.bz2".format(_hash))
    assert test_path == output


def test_no_include_recipe_config_arg(testing_metadata):
    """Two ways to not include recipe: build/include_recipe: False in meta.yaml; or this.
    Former is tested with specific recipe."""
    outputs = api.build(testing_metadata)
    assert package_has_file(outputs[0], "info/recipe/meta.yaml")

    # make sure that it is not there when the command line flag is passed
    testing_metadata.config.include_recipe = False
    testing_metadata.meta['build']['number'] = 2
    output_file = api.build(testing_metadata)[0]
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_no_include_recipe_meta_yaml(testing_metadata, testing_config):
    # first, make sure that the recipe is there by default.  This test copied from above, but copied
    # as a sanity check here.
    outputs = api.build(testing_metadata)
    assert package_has_file(outputs[0], "info/recipe/meta.yaml")

    output_file = api.build(os.path.join(metadata_dir, '_no_include_recipe'),
                            config=testing_config)[0]
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_early_abort(testing_config, capfd):
    """There have been some problems with conda-build dropping out early.
    Make sure we aren't causing them"""
    api.build(os.path.join(metadata_dir, '_test_early_abort'), config=testing_config)
    output, error = capfd.readouterr()
    assert "Hello World" in output


def test_output_build_path_git_source(testing_workdir, testing_config):
    recipe_path = os.path.join(metadata_dir, "source_git_jinja2")
    output = api.get_output_file_path(recipe_path, config=testing_config)[0]
    _hash = api.render(recipe_path, config=testing_config)[0][0]._hash_dependencies()
    test_path = os.path.join(testing_config.croot, testing_config.host_subdir,
                    "conda-build-test-source-git-jinja2-1.20.2-py{}{}{}_0_g262d444.tar.bz2".format(
                        sys.version_info.major, sys.version_info.minor, _hash))
    assert output == test_path


def test_build_with_no_activate_does_not_activate():
    api.build(os.path.join(metadata_dir, '_set_env_var_no_activate_build'), activate=False,
              anaconda_upload=False)


@pytest.mark.serial
def test_build_with_activate_does_activate():
    api.build(os.path.join(metadata_dir, '_set_env_var_activate_build'), activate=True,
              anaconda_upload=False)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="no binary prefix manipulation done on windows.")
def test_binary_has_prefix_files(testing_workdir, testing_config):
    api.build(os.path.join(metadata_dir, '_binary_has_prefix_files'), config=testing_config)


def test_relative_path_git_versioning(testing_workdir, testing_config):
    # conda_build_test_recipe is a manual step.  Clone it at the same level as
    #    your conda-build source.
    cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                       'conda_build_test_recipe'))
    tag = describe_root(cwd)
    output = api.get_output_file_path(os.path.join(metadata_dir,
                                                   "_source_git_jinja2_relative_path"),
                                      config=testing_config)[0]
    assert tag in output


def test_relative_git_url_git_versioning(testing_workdir, testing_config):
    cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                       'conda_build_test_recipe'))
    tag = describe_root(cwd)
    recipe = os.path.join(metadata_dir, "_source_git_jinja2_relative_git_url")
    output = api.get_output_file_path(recipe, config=testing_config)[0]
    assert tag in output


def test_dirty_variable_available_in_build_scripts(testing_workdir, testing_config):
    recipe = os.path.join(metadata_dir, "_dirty_skip_section")
    testing_config.dirty = True
    api.build(recipe, config=testing_config)

    with pytest.raises(subprocess.CalledProcessError):
        testing_config.dirty = False
        api.build(recipe, config=testing_config)


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


def test_checkout_tool_as_dependency(testing_workdir, testing_config, monkeypatch):
    # temporarily necessary because we have custom rebuilt svn for longer prefix here
    testing_config.channel_urls = ('conda_build_test', )
    # "hide" svn by putting a known bad one on PATH
    exename = dummy_executable(testing_workdir, "svn")
    monkeypatch.setenv("PATH", testing_workdir, prepend=os.pathsep)
    FNULL = open(os.devnull, 'w')
    with pytest.raises(subprocess.CalledProcessError, message="Dummy svn was not executed"):
        check_call_env([exename, '--version'], stderr=FNULL)
    FNULL.close()
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([testing_workdir, env["PATH"]])
    api.build(os.path.join(metadata_dir, '_checkout_tool_as_dependency'), config=testing_config)


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
def test_build_msvc_compiler(msvc_ver, monkeypatch):
    # verify that the correct compiler is available
    cl_versions = {"9.0": 15,
                   "10.0": 16,
                   "11.0": 17,
                   "12.0": 18,
                   "14.0": 19}

    monkeypatch.setenv('CONDATEST_MSVC_VER', msvc_ver)
    monkeypatch.setenv('CL_EXE_VERSION', str(cl_versions[msvc_ver]))

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
def test_cmake_generator(platform, target_compiler, testing_workdir, testing_config):
    testing_config.variant['python'] = target_compiler
    api.build(os.path.join(metadata_dir, '_cmake_generator'), config=testing_config)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="No windows symlinks")
def test_symlink_fail(testing_workdir, testing_config, capfd):
    with pytest.raises(SystemExit):
        api.build(os.path.join(fail_dir, "symlinks"), config=testing_config)
    output, error = capfd.readouterr()
    assert error.count("Error") == 6, "did not find appropriate count of Error in: " + error


def test_pip_in_meta_yaml_fail(testing_workdir, testing_config):
    with pytest.raises(ValueError) as exc:
        api.build(os.path.join(fail_dir, "pip_reqs_fail_informatively"), config=testing_config)
        assert "environment.yml" in str(exc)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows doesn't show this error")
def test_broken_conda_meta(testing_workdir, testing_config):
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(fail_dir, "conda-meta"), config=testing_config)
        assert "Error: Untracked file(s) ('conda-meta/nope',)" in str(exc)


def test_recursive_fail(testing_workdir, testing_config):
    with pytest.raises(RuntimeError) as exc:
        api.build(os.path.join(fail_dir, "recursive-build"), config=testing_config)
    # indentation critical here.  If you indent this, and the exception is not raised, then
    #     the exc variable here isn't really completely created and shows really strange errors:
    #     AttributeError: 'ExceptionInfo' object has no attribute 'typename'
    assert "recursive-build2" in str(exc.value)


def test_jinja_typo(testing_workdir, testing_config):
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(fail_dir, "source_git_jinja2_oops"), config=testing_config)
    assert "GIT_DSECRIBE_TAG" in exc.exconly()


@pytest.mark.serial
def test_skip_existing(testing_workdir, testing_config, capfd):
    # build the recipe first
    api.build(empty_sections, config=testing_config)
    api.build(empty_sections, config=testing_config, skip_existing=True)
    output, error = capfd.readouterr()
    assert "is already built" in output


@pytest.mark.serial
def test_skip_existing_url(testing_metadata, testing_workdir, capfd):
    # make sure that it is built
    outputs = api.build(testing_metadata)

    # Copy our package into some new folder
    output_dir = os.path.join(testing_workdir, 'someoutput')
    platform = os.path.join(output_dir, testing_metadata.config.host_subdir)
    os.makedirs(platform)
    copy_into(outputs[0], os.path.join(platform, os.path.basename(outputs[0])))

    # create the index so conda can find the file
    api.update_index(platform, config=testing_metadata.config)

    # HACK: manually create noarch location there, so that conda 4.3.2+ considers a valid channel
    noarch = os.path.join(output_dir, 'noarch')
    os.makedirs(noarch)
    api.update_index(noarch, config=testing_metadata.config)

    testing_metadata.config.skip_existing = True
    testing_metadata.config.channel_urls = [url_path(output_dir)]

    api.build(testing_metadata)

    output, error = capfd.readouterr()
    assert "is already built" in output
    assert url_path(testing_metadata.config.croot) in output


def test_failed_tests_exit_build(testing_workdir, testing_config):
    """https://github.com/conda/conda-build/issues/1112"""
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(metadata_dir, "_test_failed_test_exits"), config=testing_config)
        assert 'TESTS FAILED' in exc


def test_requirements_txt_for_run_reqs(testing_workdir, testing_config):
    """
    If run reqs are blank, then conda-build looks for requirements.txt in the recipe folder.
    There has been a report of issue with unsatisfiable requirements at

    https://github.com/Anaconda-Platform/anaconda-server/issues/2565

    This test attempts to reproduce those conditions: a channel other than defaults with this
    requirements.txt
    """
    testing_config.channel_urls = ('conda_build_test', )
    api.build(os.path.join(metadata_dir, "_requirements_txt_run_reqs"), config=testing_config)


def test_compileall_compiles_all_good_files(testing_workdir, testing_config):
    output = api.build(os.path.join(metadata_dir, "_compile-test"), config=testing_config)[0]
    good_files = ['f1.py', 'f3.py']
    bad_file = 'f2_bad.py'
    for f in good_files:
        assert package_has_file(output, f)
        # look for the compiled file also
        assert package_has_file(output, add_mangling(f))
    assert package_has_file(output, bad_file)
    assert not package_has_file(output, add_mangling(bad_file))


def test_render_setup_py_old_funcname(testing_workdir, testing_config, caplog):
    logging.basicConfig(level=logging.INFO)
    api.build(os.path.join(metadata_dir, "_source_setuptools"), config=testing_config)
    assert "Deprecation notice: the load_setuptools function has been renamed to " in caplog.text


def test_debug_build_option(testing_metadata, caplog, capfd):
    logging.basicConfig(level=logging.INFO)
    info_message = "INFO"
    debug_message = "DEBUG"
    testing_metadata.config.debug = False
    testing_metadata.config.verbose = False
    api.build(testing_metadata)
    # this comes from an info message
    assert info_message in caplog.text
    # this comes from a debug message
    assert debug_message not in caplog.text

    testing_metadata.config.debug = True
    api.build(testing_metadata)
    # this comes from an info message
    assert info_message in caplog.text
    # this comes from a debug message
    assert debug_message in caplog.text


@pytest.mark.skipif(not on_win, reason="only Windows is insane enough to have backslashes in paths")
def test_backslash_in_always_include_files_path(testing_config):
    api.build(os.path.join(metadata_dir, '_backslash_in_include_files'))
    with pytest.raises(RuntimeError):
        api.build(os.path.join(fail_dir, 'backslash_in_include_files'))


def test_build_metadata_object(testing_metadata):
    api.build(testing_metadata)


@pytest.mark.skipif(on_win, reason="fortran compilers on win are hard.")
def test_numpy_setup_py_data(testing_config):
    recipe_path = os.path.join(metadata_dir, '_numpy_setup_py_data')
    _hash = api.render(recipe_path, config=testing_config, numpy="1.10")[0][0]._hash_dependencies()
    assert os.path.basename(api.get_output_file_path(recipe_path,
                            config=testing_config, numpy="1.10")[0]) == \
                            "load_setup_py_test-1.0a1-py{0}{1}np110{2}_1.tar.bz2".format(
                                sys.version_info.major, sys.version_info.minor, _hash)


def test_relative_git_url_submodule_clone(testing_workdir, monkeypatch):
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
    monkeypatch.setenv("PATH", testing_workdir, prepend=os.pathsep)
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
            check_call_env([git, 'init'], env=sys_git_env)
        with open('absolute', 'w') as f:
            f.write(str(tag))
        check_call_env([git, 'add', 'absolute'], env=sys_git_env)
        check_call_env([git, 'commit', '-m', 'absolute{}'.format(tag)],
                                env=sys_git_env)

        os.chdir(relative_sub)
        if tag == 0:
            check_call_env([git, 'init'], env=sys_git_env)
        with open('relative', 'w') as f:
            f.write(str(tag))
        check_call_env([git, 'add', 'relative'], env=sys_git_env)
        check_call_env([git, 'commit', '-m', 'relative{}'.format(tag)],
                                env=sys_git_env)

        os.chdir(toplevel)
        if tag == 0:
            check_call_env([git, 'init'], env=sys_git_env)
        with open('toplevel', 'w') as f:
            f.write(str(tag))
        check_call_env([git, 'add', 'toplevel'], env=sys_git_env)
        check_call_env([git, 'commit', '-m', 'toplevel{}'.format(tag)],
                                env=sys_git_env)
        if tag == 0:
            check_call_env([git, 'submodule', 'add',
                            convert_path_for_cygwin_or_msys2(git, absolute_sub), 'absolute'],
                           env=sys_git_env)
            check_call_env([git, 'submodule', 'add', '../relative_sub', 'relative'],
                           env=sys_git_env)
        else:
            # Once we use a more recent Git for Windows than 2.6.4 on Windows or m2-git we
            # can change this to `git submodule update --recursive`.
            check_call_env([git, 'submodule', 'foreach', git, 'pull'], env=sys_git_env)
        check_call_env([git, 'commit', '-am', 'added submodules@{}'.format(tag)],
                              env=sys_git_env)
        check_call_env([git, 'tag', '-a', str(tag), '-m', 'tag {}'.format(tag)],
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
                 ['git --no-pager submodule --quiet foreach git log -n 1 --pretty=format:%%s > '
                       '%PREFIX%\\summaries.txt  # [win]',
                  'git --no-pager submodule --quiet foreach git log -n 1 --pretty=format:%s > '
                       '$PREFIX/summaries.txt   # [not win]'])
            ])),
            ('test', OrderedDict([
                ('commands',
                 ['echo absolute{}relative{} > %PREFIX%\\expected_summaries.txt       # [win]'
                      .format(tag, tag),
                  'fc.exe /W %PREFIX%\\expected_summaries.txt %PREFIX%\\summaries.txt # [win]',
                  'echo absolute{}relative{} > $PREFIX/expected_summaries.txt         # [not win]'
                      .format(tag, tag),
                  'diff -wuN ${PREFIX}/expected_summaries.txt ${PREFIX}/summaries.txt # [not win]'])
            ]))
        ])

        with open(filename, 'w') as outfile:
            outfile.write(yaml.dump(data, default_flow_style=False, width=999999999))
        # Reset the path because our broken, dummy `git` would cause `render_recipe`
        # to fail, while no `git` will cause the build_dependencies to be installed.
        monkeypatch.undo()
        # This will (after one spin round the loop) install and run 'git' with the
        # build env prepended to os.environ[]
        output = api.get_output_file_path(testing_workdir)[0]
        assert ("relative_submodules-{}-".format(tag) in output)
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
        output = api.get_output_file_path(testing_workdir)[0]
        assert (os.path.sep + "noarch" + os.path.sep in output or not noarch)
        assert (os.path.sep + "noarch" + os.path.sep not in output or noarch)


def test_disable_pip(testing_config, testing_metadata):
    testing_metadata.disable_pip = True
    testing_metadata.meta['build']['script'] = 'python -c "import pip; print(pip.__version__)"'
    with pytest.raises(subprocess.CalledProcessError):
        api.build(testing_metadata)

    testing_metadata.meta['build']['script'] = ('python -c "import setuptools; '
                                                'print(setuptools.__version__)"')
    with pytest.raises(subprocess.CalledProcessError):
        api.build(testing_metadata)


@pytest.mark.skipif(not sys.platform.startswith('linux'),
                    reason="rpath fixup only done on Linux so far.")
def test_rpath_linux(testing_config):
    api.build(os.path.join(metadata_dir, "_rpath"), config=testing_config)


def test_noarch_none_value(testing_workdir, testing_config):
    recipe = os.path.join(metadata_dir, "_noarch_none")
    with pytest.raises(exceptions.CondaBuildException):
        api.build(recipe, config=testing_config)


def test_noarch_foo_value(testing_config):
    outputs = api.build(os.path.join(metadata_dir, "noarch_generic"), config=testing_config)
    metadata = json.loads(package_has_file(outputs[0], 'info/index.json').decode())
    assert metadata['noarch'] == "generic"


def test_about_json_content(testing_metadata):
    outputs = api.build(testing_metadata)
    about = json.loads(package_has_file(outputs[0], 'info/about.json').decode())
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


@pytest.mark.xfail(not conda_43(), reason="new noarch supported starting with conda 4.3")
def test_noarch_python_with_tests(testing_config):
    recipe = os.path.join(metadata_dir, "_noarch_python_with_tests")
    api.build(recipe, config=testing_config)


def test_noarch_python_1(testing_config):
    outputs = api.build(os.path.join(metadata_dir, "_noarch_python"), config=testing_config)
    assert package_has_file(outputs[0], 'info/files') is not ''
    extra = json.loads(package_has_file(outputs[0], 'info/package_metadata.json').decode())
    assert 'noarch' in extra
    assert 'entry_points' in extra['noarch']
    assert 'type' in extra['noarch']
    assert 'package_metadata_version' in extra


def test_legacy_noarch_python(testing_config):
    output = api.build(os.path.join(metadata_dir, "_legacy_noarch_python"),
                       config=testing_config)[0]
    # make sure that the package is going into the noarch folder
    assert os.path.basename(os.path.dirname(output)) == 'noarch'


def test_preferred_env(testing_config):
    recipe = os.path.join(metadata_dir, "_preferred_env")
    output = api.build(recipe, config=testing_config)[0]
    extra = json.loads(package_has_file(output, 'info/package_metadata.json').decode())
    assert 'preferred_env' in extra
    assert 'name' in extra['preferred_env']
    assert 'executable_paths' in extra['preferred_env']
    exe_paths = extra['preferred_env']['executable_paths']
    if on_win:
        assert exe_paths == ['Scripts/exepath1.bat', 'Scripts/exepath2.bat']
    else:
        assert exe_paths == ['bin/exepath1', 'bin/exepath2']
    assert 'package_metadata_version' in extra


def test_skip_compile_pyc(testing_config):
    outputs = api.build(os.path.join(metadata_dir, "skip_compile_pyc"), config=testing_config)
    tf = tarfile.open(outputs[0])
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


def test_detect_binary_files_with_prefix(testing_config):
    outputs = api.build(os.path.join(metadata_dir, "_detect_binary_files_with_prefix"),
                        config=testing_config)
    matches = []
    with tarfile.open(outputs[0]) as tf:
        has_prefix = tf.extractfile('info/has_prefix')
        contents = [p.strip().decode('utf-8') for p in
                    has_prefix.readlines()]
        has_prefix.close()
        matches = [entry for entry in contents if entry.endswith('binary-has-prefix') or
                                                  entry.endswith('"binary-has-prefix"')]
    assert len(matches) == 1, "binary-has-prefix not recorded in info/has_prefix"
    assert ' binary ' in matches[0], "binary-has-prefix not recorded as binary in info/has_prefix"


def test_skip_detect_binary_files_with_prefix(testing_config):
    recipe = os.path.join(metadata_dir, "_skip_detect_binary_files_with_prefix")
    outputs = api.build(recipe, config=testing_config)
    matches = []
    with tarfile.open(outputs[0]) as tf:
        try:
            has_prefix = tf.extractfile('info/has_prefix')
            contents = [p.strip().decode('utf-8') for p in
                        has_prefix.readlines()]
            has_prefix.close()
            matches = [entry for entry in contents if entry.endswith('binary-has-prefix') or
                                                      entry.endswith('"binary-has-prefix"')]
        except:
            pass
    assert len(matches) == 0, "binary-has-prefix recorded in info/has_prefix despite:" \
                              "build/detect_binary_files_with_prefix: false"


def test_fix_permissions(testing_config):
    recipe = os.path.join(metadata_dir, "fix_permissions")
    outputs = api.build(recipe, config=testing_config)
    with tarfile.open(outputs[0]) as tf:
        for f in tf.getmembers():
            assert f.mode & 0o444 == 0o444, "tar member '{}' has invalid (read) mode".format(f.name)


@pytest.mark.skipif(not on_win, reason="windows-only functionality")
@pytest.mark.parametrize('recipe_name', ["_script_win_creates_exe",
                                         "_script_win_creates_exe_garbled"])
def test_script_win_creates_exe(testing_config, recipe_name):
    recipe = os.path.join(metadata_dir, recipe_name)
    outputs = api.build(recipe, config=testing_config)
    assert package_has_file(outputs[0], 'Scripts/test-script.exe')
    assert package_has_file(outputs[0], 'Scripts/test-script-script.py')


def test_output_folder_moves_file(testing_metadata, testing_workdir):
    testing_metadata.config.output_folder = testing_workdir
    outputs = api.build(testing_metadata, no_test=True)
    assert outputs[0].startswith(testing_workdir)


def test_info_files_json(testing_config):
    outputs = api.build(os.path.join(metadata_dir, "ignore_some_prefix_files"),
                        config=testing_config)
    assert package_has_file(outputs[0], "info/paths.json")
    with tarfile.open(outputs[0]) as tf:
        data = json.loads(tf.extractfile('info/paths.json').read().decode('utf-8'))
    fields = ["_path", "sha256", "size_in_bytes", "path_type", "file_mode", "no_link",
              "prefix_placeholder", "inode_paths"]
    for key in data.keys():
        assert key in ['paths', 'paths_version']
    for paths in data.get('paths'):
        for field in paths.keys():
            assert field in fields
    assert len(data.get('paths')) == 2
    for file in data.get('paths'):
        for key in file.keys():
            assert key in fields
        short_path = file.get("_path")
        if short_path == "test.sh" or short_path == "test.bat":
            assert file.get("prefix_placeholder") is not None
            assert file.get("file_mode") is not None
        else:
            assert file.get("prefix_placeholder") is None
            assert file.get("file_mode") is None


def test_build_expands_wildcards(mocker, testing_workdir):
    build_tree = mocker.patch("conda_build.build.build_tree")
    config = api.Config()
    files = ['abc', 'acb']
    for f in files:
        os.makedirs(f)
        with open(os.path.join(f, 'meta.yaml'), 'w') as fh:
            fh.write('\n')
    api.build(["a*"], config=config)
    output = [os.path.join(os.getcwd(), path, 'meta.yaml') for path in files]
    build_tree.assert_called_once_with(output, post=None, need_source_download=True,
                                       build_only=False, notest=False, config=config,
                                       variants=None)


@pytest.mark.serial
def test_remove_workdir_default(testing_config, caplog):
    recipe = os.path.join(metadata_dir, '_keep_work_dir')
    api.build(recipe, config=testing_config)
    assert not glob(os.path.join(testing_config.work_dir, '*'))


@pytest.mark.serial
def test_keep_workdir(testing_config, caplog):
    recipe = os.path.join(metadata_dir, '_keep_work_dir')
    api.build(recipe, config=testing_config, dirty=True, remove_work_dir=False, debug=True)
    assert "Not removing work directory after build" in caplog.text
    assert glob(os.path.join(testing_config.work_dir, '*'))
    testing_config.clean()


@pytest.mark.serial
def test_workdir_removal_warning(testing_config, caplog):
    recipe = os.path.join(metadata_dir, '_test_uses_src_dir')
    with pytest.raises(ValueError) as exc:
        api.build(recipe, config=testing_config)
        assert "work dir is removed" in str(exc)


@pytest.mark.serial
def test_workdir_removal_warning_no_remove(testing_config, caplog):
    recipe = os.path.join(metadata_dir, '_test_uses_src_dir')
    api.build(recipe, config=testing_config, remove_work_dir=False)
    assert "Not removing work directory after build" in caplog.text


@pytest.mark.skipif(not sys.platform.startswith('linux'),
                    reason="cross compiler packages created only on Linux right now")
@pytest.mark.xfail(VersionOrder(conda.__version__) < VersionOrder('4.3.2'),
                   reason="subdir support only in later versions of conda")
def test_cross_compiler(testing_workdir, testing_config, caplog):
    # TODO: testing purposes.  Package on @mingwandroid's channel.
    testing_config.channel_urls = ('rdonnelly', )
    # activation is necessary to set the appropriate toolchain env vars
    testing_config.activate = True
    # testing_config.debug = True
    recipe_dir = os.path.join(metadata_dir, '_cross_helloworld')
    output = api.build(recipe_dir, config=testing_config)[0]
    assert output.startswith(os.path.join(testing_config.croot, 'linux-imx351uc'))
    api.build(recipe, config=testing_config, remove_work_dir=False)
    assert "Not removing work directory after build" in caplog.text


@pytest.mark.skipif(sys.platform != 'darwin', reason="relevant to mac only")
def test_append_python_app_osx(testing_config):
    """Recipes that use osx_is_app need to have python.app in their runtime requirements."""
    recipe = os.path.join(metadata_dir, '_nexpy')
    # tests will fail here if python.app is not added to the run reqs by conda-build, because
    #    without it, pythonw will be missing.
    api.build(recipe, config=testing_config, channel_urls=('nexpy', ))


# Not sure about this behavior.  Basically, people need to realize that if they start with a recipe from disk,
#    they should not then alter the metadata object.  Later reparsing will clobber their edits to the object.
# The complicated thing is that these edits are indistinguishable from Jinja2 templating doing its normal thing.

# def test_clobbering_manually_set_metadata_raises(testing_metadata, testing_workdir):
#     api.output_yaml(testing_metadata, 'meta.yaml')
#     metadata = api.render(testing_workdir)[0][0]
#     # make the package meta dict out of sync with file contents
#     metadata.meta['package']['name'] = 'steve'
#     # re-render happens as part of build.  We should see an error about clobbering our customized
#     #    meta dict
#     with pytest.raises(ValueError):
#         api.build(metadata)


def test_pin_downstream(testing_metadata, testing_config):
    outputs = api.build(os.path.join(metadata_dir, '_pin_downstream'), config=testing_config)
    testing_metadata.meta['requirements']['build'] = ['test_has_pin_downstream']
    testing_metadata.config.index = None
    m = finalize_metadata(testing_metadata)
    assert 'a 1.0' in m.meta['requirements']['run']

def test_pin_subpackage_exact(testing_config):
    m = api.render(os.path.join(metadata_dir, '_pin_subpackage_exact'), config=testing_config)[0][0]
    assert 'pin_downstream_subpkg 1.0 hbf21a9e_0' in m.meta['requirements']['run']
