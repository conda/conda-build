"""
This module tests the build API.  These are high-level integration tests.
"""

import base64
from collections import OrderedDict
from glob import glob
import logging
import os
import re
import subprocess
import sys
import json
import uuid

# for version
import conda

from conda_build.conda_interface import PY3, url_path, LinkError, CondaError, cc_conda_build
import conda_build

from binstar_client.commands import remove, show
from binstar_client.errors import NotFound
from pkg_resources import parse_version
import pytest
import yaml
import tarfile

from conda_build import api, exceptions, __version__
from conda_build.build import VersionOrder
from conda_build.render import finalize_metadata
from conda_build.utils import (copy_into, on_win, check_call_env, convert_path_for_cygwin_or_msys2,
                               package_has_file, check_output_env, get_conda_operation_locks, rm_rf,
                               walk, env_var)
from conda_build.os_utils.external import find_executable
from conda_build.exceptions import DependencyNeedsBuildingError, CondaBuildException
from conda_build.conda_interface import reset_context
from conda.exceptions import ClobberError, CondaMultiError
from conda_build.conda_interface import conda_46

from .utils import is_valid_dir, metadata_dir, fail_dir, add_mangling, FileNotFoundError

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


def test_token_upload(testing_workdir, testing_metadata):
    folder_uuid = uuid.uuid4().hex
    # generated with conda_test_account user, command:
    #    anaconda auth --create --name CONDA_BUILD_UPLOAD_TEST --scopes 'api repos conda'
    args = AnacondaClientArgs(specs="conda_build_test/test_token_upload_" + folder_uuid,
                              token="co-143399b8-276e-48db-b43f-4a3de839a024",
                              force=True)

    with pytest.raises(NotFound):
        show.main(args)

    testing_metadata.meta['package']['name'] = '_'.join([testing_metadata.name(), folder_uuid])
    testing_metadata.config.token = args.token

    # the folder with the test recipe to upload
    api.build(testing_metadata, notest=True)

    # make sure that the package is available (should raise if it doesn't)
    show.main(args)

    # clean up - we don't actually want this package to exist
    remove.main(args)

    # verify cleanup:
    with pytest.raises(NotFound):
        show.main(args)


@pytest.mark.parametrize("service_name", ["binstar", "anaconda"])
def test_no_anaconda_upload_condarc(service_name, testing_workdir, testing_config, capfd):
    api.build(empty_sections, config=testing_config, notest=True)
    output, error = capfd.readouterr()
    assert "Automatic uploading is disabled" in output, error


def test_git_describe_info_on_branch(testing_config):
    recipe_path = os.path.join(metadata_dir, "_git_describe_number_branch")
    m = api.render(recipe_path, config=testing_config)[0][0]
    output = api.get_output_file_path(m)[0]
    # missing hash because we set custom build string in meta.yaml
    test_path = os.path.join(testing_config.croot, testing_config.host_subdir,
                    "git_describe_number_branch-1.20.2.0-1_g82c6ba6.tar.bz2")
    assert test_path == output


def test_no_include_recipe_config_arg(testing_metadata):
    """Two ways to not include recipe: build/include_recipe: False in meta.yaml; or this.
    Former is tested with specific recipe."""
    outputs = api.build(testing_metadata)
    assert package_has_file(outputs[0], "info/recipe/meta.yaml")

    # make sure that it is not there when the command line flag is passed
    testing_metadata.config.include_recipe = False
    testing_metadata.meta['build']['number'] = 2
    # We cannot test packages without recipes as we cannot render them
    output_file = api.build(testing_metadata, notest=True)[0]
    assert not package_has_file(output_file, "info/recipe/meta.yaml")


def test_no_include_recipe_meta_yaml(testing_metadata, testing_config):
    # first, make sure that the recipe is there by default.  This test copied from above, but copied
    # as a sanity check here.
    outputs = api.build(testing_metadata, notest=True)
    assert package_has_file(outputs[0], "info/recipe/meta.yaml")

    output_file = api.build(os.path.join(metadata_dir, '_no_include_recipe'),
                            config=testing_config, notest=True)[0]
    assert not package_has_file(output_file, "info/recipe/meta.yaml")

    with pytest.raises(SystemExit):
        # we are testing that even with the recipe excluded, we still get the tests in place
        output_file = api.build(os.path.join(metadata_dir, '_no_include_recipe'),
                                config=testing_config)[0]


def test_early_abort(testing_config, capfd):
    """There have been some problems with conda-build dropping out early.
    Make sure we aren't causing them"""
    api.build(os.path.join(metadata_dir, '_test_early_abort'), config=testing_config)
    output, error = capfd.readouterr()
    assert "Hello World" in output


def test_output_build_path_git_source(testing_workdir, testing_config):
    recipe_path = os.path.join(metadata_dir, "source_git_jinja2")
    m = api.render(recipe_path, config=testing_config)[0][0]
    output = api.get_output_file_paths(m)[0]
    _hash = m.hash_dependencies()
    test_path = os.path.join(testing_config.croot, testing_config.host_subdir,
                    "conda-build-test-source-git-jinja2-1.20.2-py{}{}{}_0_g262d444.tar.bz2".format(
                        sys.version_info.major, sys.version_info.minor, _hash))
    assert output == test_path


def test_build_with_no_activate_does_not_activate():
    api.build(os.path.join(metadata_dir, '_set_env_var_no_activate_build'), activate=False,
              anaconda_upload=False)


@pytest.mark.xfail(on_win and len(os.getenv('PATH')) > 1024, reason="Long paths make activation fail with obscure messages")
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
    platforms = sorted(list(set(["32", ] + platforms)))
    compilers = ["2.7", "3.5"]
    msvc_vers = ['9.0', '14.0']
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
    with pytest.raises((SystemExit, FileNotFoundError)):
        api.build(os.path.join(fail_dir, "symlinks"), config=testing_config)
    # output, error = capfd.readouterr()
    # assert error.count("Error") == 6, "did not find appropriate count of Error in: " + error


def test_pip_in_meta_yaml_fail(testing_workdir, testing_config):
    with pytest.raises(ValueError) as exc:
        api.build(os.path.join(fail_dir, "pip_reqs_fail_informatively"), config=testing_config)
    assert "environment.yml" in str(exc)


def test_recursive_fail(testing_workdir, testing_config):
    with pytest.raises((RuntimeError, exceptions.DependencyNeedsBuildingError)) as exc:
        api.build(os.path.join(fail_dir, "recursive-build"), config=testing_config)
    # indentation critical here.  If you indent this, and the exception is not raised, then
    #     the exc variable here isn't really completely created and shows really strange errors:
    #     AttributeError: 'ExceptionInfo' object has no attribute 'typename'
    assert "recursive-build2" in str(exc.value)


def test_jinja_typo(testing_workdir, testing_config):
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(fail_dir, "source_git_jinja2_oops"), config=testing_config)
    assert "GIT_DSECRIBE_TAG" in exc.exconly()


def test_skip_existing(testing_workdir, testing_config, capfd):
    # build the recipe first
    api.build(empty_sections, config=testing_config)
    api.build(empty_sections, config=testing_config, skip_existing=True)
    output, error = capfd.readouterr()
    assert "are already built" in output


def test_skip_existing_url(testing_metadata, testing_workdir, capfd):
    # make sure that it is built
    outputs = api.build(testing_metadata)

    # Copy our package into some new folder
    output_dir = os.path.join(testing_workdir, 'someoutput')
    platform = os.path.join(output_dir, testing_metadata.config.host_subdir)
    os.makedirs(platform)
    copy_into(outputs[0], os.path.join(platform, os.path.basename(outputs[0])))

    # create the index so conda can find the file
    api.update_index(output_dir)

    testing_metadata.config.skip_existing = True
    testing_metadata.config.channel_urls = [url_path(output_dir)]

    api.build(testing_metadata)

    output, error = capfd.readouterr()
    assert "are already built" in output
    assert url_path(testing_metadata.config.croot) in output


def test_failed_tests_exit_build(testing_workdir, testing_config):
    """https://github.com/conda/conda-build/issues/1112"""
    with pytest.raises(SystemExit) as exc:
        api.build(os.path.join(metadata_dir, "_test_failed_test_exits"), config=testing_config)
    assert 'TESTS FAILED' in str(exc)


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
    api.build(os.path.join(metadata_dir, "_source_setuptools"), config=testing_config)
    assert "Deprecation notice: the load_setuptools function has been renamed to " in caplog.text


@pytest.mark.skipif(not on_win, reason="only Windows is insane enough to have backslashes in paths")
def test_backslash_in_always_include_files_path(testing_config):
    api.build(os.path.join(metadata_dir, '_backslash_in_include_files'))
    with pytest.raises(RuntimeError):
        api.build(os.path.join(fail_dir, 'backslash_in_include_files'))


def test_build_metadata_object(testing_metadata):
    api.build(testing_metadata)


def test_numpy_setup_py_data(testing_config):
    recipe_path = os.path.join(metadata_dir, '_numpy_setup_py_data')
    subprocess.call('conda remove -y cython'.split())
    with pytest.raises(CondaBuildException) as exc:
        m = api.render(recipe_path, config=testing_config, numpy="1.11")[0][0]
        assert "Cython" in str(exc)
    subprocess.check_call('conda install -y cython'.split())
    m = api.render(recipe_path, config=testing_config, numpy="1.11")[0][0]
    _hash = m.hash_dependencies()
    assert os.path.basename(api.get_output_file_path(m)[0]) == \
                            "load_setup_py_test-0.1.0-np111py{0}{1}{2}_0.tar.bz2".format(
                                sys.version_info.major, sys.version_info.minor, _hash)


def test_relative_git_url_submodule_clone(testing_workdir, testing_config, monkeypatch):
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

        recipe_dir = os.path.join(testing_workdir, 'recipe')
        if not os.path.exists(recipe_dir):
            os.makedirs(recipe_dir)
        filename = os.path.join(testing_workdir, 'recipe', 'meta.yaml')
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
        metadata = api.render(testing_workdir, config=testing_config)[0][0]
        output = api.get_output_file_path(metadata, config=testing_config)[0]
        assert ("relative_submodules-{}-".format(tag) in output)
        api.build(metadata, config=testing_config)


def test_noarch(testing_workdir):
    filename = os.path.join(testing_workdir, 'meta.yaml')
    for noarch in (False, True):
        data = OrderedDict([
            ('package', OrderedDict([
                ('name', 'test'),
                ('version', '0.0.0')])),
            ('build', OrderedDict([
                 ('noarch', noarch)]))
            ])
        with open(filename, 'w') as outfile:
            outfile.write(yaml.dump(data, default_flow_style=False, width=999999999))
        output = api.get_output_file_path(testing_workdir)[0]
        assert (os.path.sep + "noarch" + os.path.sep in output or not noarch)
        assert (os.path.sep + "noarch" + os.path.sep not in output or noarch)


def test_disable_pip(testing_config, testing_metadata):
    testing_metadata.config.disable_pip = True
    testing_metadata.meta['requirements'] = {'host': ['python'],
                                             'run': ['python']}
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


@pytest.mark.xfail(parse_version(conda.__version__) < parse_version("4.3.14"),
                   reason="new noarch supported starting with conda 4.3.14")
def test_noarch_python_with_tests(testing_config):
    recipe = os.path.join(metadata_dir, "_noarch_python_with_tests")
    api.build(recipe, config=testing_config)


def test_noarch_python_1(testing_config):
    output = api.build(os.path.join(metadata_dir, "_noarch_python"), config=testing_config)[0]
    assert package_has_file(output, 'info/files') is not ''
    extra = json.loads(package_has_file(output, 'info/link.json').decode())
    assert 'noarch' in extra
    assert 'entry_points' in extra['noarch']
    assert 'type' in extra['noarch']
    assert 'package_metadata_version' in extra


def test_legacy_noarch_python(testing_config):
    output = api.build(os.path.join(metadata_dir, "_legacy_noarch_python"),
                       config=testing_config)[0]
    # make sure that the package is going into the noarch folder
    assert os.path.basename(os.path.dirname(output)) == 'noarch'


@pytest.mark.skipif(True,
                    reason="Re-enable when private application environments are fully implemented "
                           "in conda. "
                           "See https://github.com/conda/conda/issues/3912#issuecomment-374820599")
def test_preferred_env(testing_config):
    recipe = os.path.join(metadata_dir, "_preferred_env")
    output = api.build(recipe, config=testing_config)[0]
    extra = json.loads(package_has_file(output, 'info/link.json').decode())
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
    build_tree.assert_called_once_with(output,
                                       mocker.ANY,  # config
                                       mocker.ANY,  # stats
                                       build_only=False,
                                       need_source_download=True, notest=False,
                                       post=None, variants=None)


@pytest.mark.parametrize('set_build_id', [True, False])
def test_remove_workdir_default(testing_config, caplog, set_build_id):
    recipe = os.path.join(metadata_dir, '_keep_work_dir')
    # make a metadata object - otherwise the build folder is computed within the build, but does
    #    not alter the config object that is passed in.  This is by design - we always make copies
    #    of the config object rather than edit it in place, so that variants don't clobber one
    #    another
    metadata = api.render(recipe, config=testing_config)[0][0]
    api.build(metadata, set_build_id=set_build_id)
    assert not glob(os.path.join(metadata.config.work_dir, '*'))


def test_keep_workdir_and_dirty_reuse(testing_config, capfd):
    recipe = os.path.join(metadata_dir, '_keep_work_dir')
    # make a metadata object - otherwise the build folder is computed within the build, but does
    #    not alter the config object that is passed in.  This is by design - we always make copies
    #    of the config object rather than edit it in place, so that variants don't clobber one
    #    another

    metadata = api.render(recipe, config=testing_config, dirty=True, remove_work_dir=False)[0][0]
    workdir = metadata.config.work_dir
    api.build(metadata)
    out, err = capfd.readouterr()
    assert glob(os.path.join(metadata.config.work_dir, '*'))

    # test that --dirty reuses the same old folder
    metadata = api.render(recipe, config=testing_config, dirty=True, remove_work_dir=False)[0][0]
    assert workdir == metadata.config.work_dir

    # test that without --dirty, we don't reuse the folder
    metadata = api.render(recipe, config=testing_config)[0][0]
    assert workdir != metadata.config.work_dir

    testing_config.clean()


def test_workdir_removal_warning(testing_config, caplog):
    recipe = os.path.join(metadata_dir, '_test_uses_src_dir')
    with pytest.raises(ValueError) as exc:
        api.build(recipe, config=testing_config)
        assert "work dir is removed" in str(exc)


# @pytest.mark.serial
# @pytest.mark.skipif(not sys.platform.startswith('linux'),
#                     reason="cross compiler packages created only on Linux right now")
# @pytest.mark.xfail(VersionOrder(conda.__version__) < VersionOrder('4.3.2'),
#                    reason="not completely implemented yet")
# def test_cross_compiler(testing_workdir, testing_config, capfd):
#     # TODO: testing purposes.  Package from @mingwandroid's channel, copied to conda_build_test
#     testing_config.channel_urls = ('conda_build_test', )
#     # activation is necessary to set the appropriate toolchain env vars
#     testing_config.activate = True
#     # testing_config.debug = True
#     recipe_dir = os.path.join(metadata_dir, '_cross_helloworld')
#     output = api.build(recipe_dir, config=testing_config)[0]
#     assert output.startswith(os.path.join(testing_config.croot, 'linux-imx351uc'))


@pytest.mark.skipif(sys.platform != 'darwin', reason="relevant to mac only")
def test_append_python_app_osx(testing_config):
    """Recipes that use osx_is_app need to have python.app in their runtime requirements.

    conda-build will add it if it's missing."""
    recipe = os.path.join(metadata_dir, '_osx_is_app_missing_python_app')
    # tests will fail here if python.app is not added to the run reqs by conda-build, because
    #    without it, pythonw will be missing.
    api.build(recipe, config=testing_config)


# Not sure about this behavior. Basically, people need to realize that if they
#    start with a recipe from disk, they should not then alter the metadata
#    object. Later reparsing will clobber their edits to the object. The
#    complicated thing is that these edits are indistinguishable from Jinja2
#    templating doing its normal thing.

# def test_clobbering_manually_set_metadata_raises(testing_metadata, testing_workdir):
#     api.output_yaml(testing_metadata, 'meta.yaml')
#     metadata = api.render(testing_workdir)[0][0]
#     # make the package meta dict out of sync with file contents
#     metadata.meta['package']['name'] = 'steve'
#     # re-render happens as part of build.  We should see an error about clobbering our customized
#     #    meta dict
#     with pytest.raises(ValueError):
#         api.build(metadata)


def test_run_exports(testing_metadata, testing_config, testing_workdir):
    api.build(os.path.join(metadata_dir, '_run_exports'), config=testing_config, notest=True)
    api.build(os.path.join(metadata_dir, '_run_exports_implicit_weak'), config=testing_config,
              notest=True)

    # run_exports is tricky.  We mostly only ever want things in "host".  Here are the conditions:

    #    1. only build section present (legacy recipe).  Here, use run_exports from build.
    #       note that because strong_run_exports creates a host section, the weak exports from build
    #       will not apply.
    testing_metadata.meta['requirements']['build'] = ['test_has_run_exports']
    api.output_yaml(testing_metadata, 'meta.yaml')
    m = api.render(testing_workdir, config=testing_config)[0][0]
    assert 'strong_pinned_package 1.0.*' in m.meta['requirements']['run']
    assert 'weak_pinned_package 1.0.*' not in m.meta['requirements']['run']

    #    2. host present.  Use run_exports from host, ignore 'weak' ones from build.  All are
    #           weak by default.
    testing_metadata.meta['requirements']['build'] = ['test_has_run_exports_implicit_weak',
                                                      '{{ compiler("c") }}']
    testing_metadata.meta['requirements']['host'] = ['python']
    api.output_yaml(testing_metadata, 'host_present_weak/meta.yaml')
    m = api.render(os.path.join(testing_workdir, 'host_present_weak'), config=testing_config)[0][0]
    assert 'weak_pinned_package 2.0.*' not in m.meta['requirements'].get('run', [])

    #    3. host present, and deps in build have "strong" run_exports section.  use host, add
    #           in "strong" from build.
    testing_metadata.meta['requirements']['build'] = ['test_has_run_exports', '{{ compiler("c") }}']
    testing_metadata.meta['requirements']['host'] = ['test_has_run_exports_implicit_weak']
    api.output_yaml(testing_metadata, 'host_present_strong/meta.yaml')
    m = api.render(os.path.join(testing_workdir, 'host_present_strong'),
                   config=testing_config)[0][0]
    assert 'strong_pinned_package 1.0 0' in m.meta['requirements']['host']
    assert 'strong_pinned_package 1.0.*' in m.meta['requirements']['run']
    # weak one from test_has_run_exports should be excluded, since it is a build dep
    assert 'weak_pinned_package 1.0.*' not in m.meta['requirements']['run']
    # weak one from test_has_run_exports_implicit_weak should be present, since it is a host dep
    assert 'weak_pinned_package 2.0.*' in m.meta['requirements']['run']


def test_ignore_run_exports(testing_metadata, testing_config):
    # build the package with run exports for ensuring that we ignore it
    api.build(os.path.join(metadata_dir, '_run_exports'), config=testing_config,
              notest=True)
    # customize our fixture metadata with our desired changes
    testing_metadata.meta['requirements']['host'] = ['test_has_run_exports']
    testing_metadata.meta['build']['ignore_run_exports'] = ['downstream_pinned_package']
    testing_metadata.config.index = None
    m = finalize_metadata(testing_metadata)
    assert 'downstream_pinned_package 1.0' not in m.meta['requirements'].get('run', [])


def test_pin_subpackage_exact(testing_config):
    recipe = os.path.join(metadata_dir, '_pin_subpackage_exact')
    ms = api.render(recipe, config=testing_config)
    assert len(ms) == 2
    assert any(re.match(r'run_exports_subpkg\ 1\.0\ 0', req)
              for (m, _, _) in ms for req in m.meta.get('requirements', {}).get('run', []))


@pytest.mark.skipif(sys.platform != 'linux', reason="xattr code written here is specific to linux")
def test_copy_read_only_file_with_xattr(testing_config, testing_workdir):
    src_recipe = os.path.join(metadata_dir, '_xattr_copy')
    recipe = os.path.join(testing_workdir, '_xattr_copy')
    copy_into(src_recipe, recipe)
    # file is r/w for owner, but we change it to 400 after setting the attribute
    ro_file = os.path.join(recipe, 'mode_400_file')
    subprocess.check_call('setfattr -n user.attrib -v somevalue {}'.format(ro_file), shell=True)
    subprocess.check_call('chmod 400 {}'.format(ro_file), shell=True)
    api.build(recipe, config=testing_config)


def test_env_creation_fail_exits_build(testing_config):
    recipe = os.path.join(metadata_dir, '_post_link_exits_after_retry')
    with pytest.raises((RuntimeError, LinkError, CondaError)):
        api.build(recipe, config=testing_config)

    recipe = os.path.join(metadata_dir, '_post_link_exits_tests')
    with pytest.raises((RuntimeError, LinkError, CondaError)):
        api.build(recipe, config=testing_config)


def test_recursion_packages(testing_config):
    """Two packages that need to be built are listed in the recipe

    make sure that both get built before the one needing them gets built."""
    recipe = os.path.join(metadata_dir, '_recursive-build-two-packages')
    api.build(recipe, config=testing_config)


def test_recursion_layers(testing_config):
    """go two 'hops' - try to build a, but a needs b, so build b first, then come back to a"""
    recipe = os.path.join(metadata_dir, '_recursive-build-two-layers')
    api.build(recipe, config=testing_config)


@pytest.mark.skipif(sys.platform != 'win32', reason=("spaces break openssl prefix "
                                                     "replacement on *nix"))
def test_croot_with_spaces(testing_metadata, testing_workdir):
    testing_metadata.config.croot = os.path.join(testing_workdir, "space path")
    api.build(testing_metadata)


def test_unknown_selectors(testing_config):
    recipe = os.path.join(metadata_dir, 'unknown_selector')
    api.build(recipe, config=testing_config)


def test_extract_tarball_with_unicode_filename(testing_config):
    """See https://github.com/conda/conda-build/pull/1779"""
    recipe = os.path.join(metadata_dir, '_unicode_in_tarball')
    api.build(recipe, config=testing_config)


def test_failed_recipe_leaves_folders(testing_config, testing_workdir):
    recipe = os.path.join(fail_dir, 'recursive-build')
    m = api.render(recipe, config=testing_config)[0][0]
    locks = get_conda_operation_locks(m.config)
    with pytest.raises((RuntimeError, exceptions.DependencyNeedsBuildingError)):
        api.build(m)
    assert os.path.isdir(m.config.build_folder), 'build folder was removed'
    assert os.listdir(m.config.build_folder), 'build folder has no files'
    # make sure that it does not leave lock files, though, as these cause permission errors on
    #    centralized installations
    any_locks = False
    locks_list = set()
    for lock in locks:
        if os.path.isfile(lock.lock_file):
            any_locks = True
            dest_path = base64.b64decode(os.path.basename(lock.lock_file))
            if PY3 and hasattr(dest_path, 'decode'):
                dest_path = dest_path.decode()
            locks_list.add((lock.lock_file, dest_path))
    assert not any_locks, "remaining locks:\n{}".format('\n'.join('->'.join((l, r))
                                                                for (l, r) in locks_list))


def test_only_r_env_vars_defined(testing_config):
    recipe = os.path.join(metadata_dir, '_r_env_defined')
    testing_config.channel_urls = ('r', )
    api.build(recipe, config=testing_config)


def test_only_perl_env_vars_defined(testing_config):
    recipe = os.path.join(metadata_dir, '_perl_env_defined')
    testing_config.channel_urls = ('c3i_test', )
    api.build(recipe, config=testing_config)


@pytest.mark.skipif(on_win, reason='no lua package on win')
def test_only_lua_env(testing_config):
    recipe = os.path.join(metadata_dir, '_lua_env_defined')
    testing_config.channel_urls = ('conda-forge', )
    testing_config.prefix_length = 80
    testing_config.set_build_id = False
    api.build(recipe, config=testing_config)


def test_run_constrained_stores_constrains_info(testing_config):
    recipe = os.path.join(metadata_dir, '_run_constrained')
    out_file = api.build(recipe, config=testing_config)[0]
    info_contents = json.loads(package_has_file(out_file, 'info/index.json'))
    assert 'constrains' in info_contents
    assert len(info_contents['constrains']) == 1
    assert info_contents['constrains'][0] == 'bzip2  1.*'


def test_no_locking(testing_config):
    recipe = os.path.join(metadata_dir, 'source_git_jinja2')
    api.update_index(os.path.join(testing_config.croot))
    api.build(recipe, config=testing_config, locking=False)


def test_test_dependencies(testing_workdir, testing_config):
    recipe = os.path.join(fail_dir, 'check_test_dependencies')

    with pytest.raises(exceptions.DependencyNeedsBuildingError) as e:
        api.build(recipe, config=testing_config)

    assert 'Unsatisfiable dependencies for platform ' in str(e.value)
    assert 'pytest-package-does-not-exist' in str(e.value)


def test_runtime_dependencies(testing_workdir, testing_config):
    recipe = os.path.join(fail_dir, 'check_runtime_dependencies')

    with pytest.raises(exceptions.DependencyNeedsBuildingError) as e:
        api.build(recipe, config=testing_config)

    assert 'Unsatisfiable dependencies for platform ' in str(e.value)
    assert 'some-nonexistent-package1' in str(e.value)


def test_no_force_upload_condarc_setting(mocker, testing_workdir, testing_metadata):
    testing_metadata.config.anaconda_upload = True
    del testing_metadata.meta['test']
    api.output_yaml(testing_metadata, 'meta.yaml')
    call = mocker.patch.object(conda_build.build.subprocess, 'call')
    cc_conda_build['force_upload'] = False
    pkg = api.build(testing_workdir)
    assert call.called_once_with(['anaconda', 'upload', pkg])
    del cc_conda_build['force_upload']
    pkg = api.build(testing_workdir)
    assert call.called_once_with(['anaconda', 'upload', '--force', pkg])


def test_setup_py_data_in_env(testing_config):
    recipe = os.path.join(metadata_dir, '_setup_py_data_in_env')
    # should pass with any modern python (just not 3.5)
    api.build(recipe, config=testing_config)
    # make sure it fails with our special python logic
    with pytest.raises(subprocess.CalledProcessError):
        api.build(recipe, config=testing_config, python='3.4')


def test_numpy_xx(testing_config):
    recipe = os.path.join(metadata_dir, '_numpy_xx')
    api.build(recipe, config=testing_config, numpy='1.12')


def test_numpy_xx_host(testing_config):
    recipe = os.path.join(metadata_dir, '_numpy_xx_host')
    api.build(recipe, config=testing_config, numpy='1.12')


def test_python_xx(testing_config):
    recipe = os.path.join(metadata_dir, '_python_xx')
    api.build(recipe, config=testing_config, python='3.4')


def test_indirect_numpy_dependency(testing_metadata):
    testing_metadata.meta['requirements']['build'] = ['pandas']
    api.build(testing_metadata, numpy=1.13, notest=True)


def test_dependencies_with_notest(testing_workdir, testing_config):
    recipe = os.path.join(metadata_dir, '_test_dependencies')
    api.build(recipe, config=testing_config, notest=True)

    with pytest.raises(DependencyNeedsBuildingError) as excinfo:
        api.build(recipe, config=testing_config, notest=False)

    assert 'Unsatisfiable dependencies for platform' in str(excinfo.value)
    assert 'somenonexistentpackage1' in str(excinfo.value)


def test_source_cache_build(testing_workdir):
    recipe = os.path.join(metadata_dir, 'source_git_jinja2')
    config = api.Config(src_cache_root=testing_workdir)
    api.build(recipe, notest=True, config=config)

    git_cache_directory = '{}/git_cache' .format(testing_workdir)
    assert os.path.isdir(git_cache_directory)

    files = [filename for _, _, filenames in walk(git_cache_directory)
             for filename in filenames]

    assert len(files) > 0


def test_copy_test_source_files(testing_config):
    recipe = os.path.join(metadata_dir, '_test_test_source_files')
    filenames = set()
    for copy in (False, True):
        testing_config.copy_test_source_files = copy
        outputs = api.build(recipe, notest=False, config=testing_config)
        filenames.add(os.path.basename(outputs[0]))
        tf = tarfile.open(outputs[0])
        found = False
        files = []
        for f in tf.getmembers():
            files.append(f.name)
            # nesting of test/test here is because info/test is the main folder
            # for test files, then test is the source_files folder we specify,
            # and text.txt is within that.
            if f.name == 'info/test/test_files_folder/text.txt':
                found = True
                break
        if found:
            assert copy, "'info/test/test_files_folder/text.txt' found in tar.bz2 but not copying test source files"
            if copy:
                api.test(outputs[0])
            else:
                with pytest.raises(RuntimeError):
                    api.test(outputs[0])
        else:
            assert not copy, "'info/test/test_files_folder/text.txt' not found in tar.bz2 but copying test source files. File list: %r" % files


def test_copy_test_source_files_deps(testing_config):
    recipe = os.path.join(metadata_dir, '_test_test_source_files')
    for copy in (False, True):
        testing_config.copy_test_source_files = copy
        # test is that pytest is a dep either way.  Builds will fail if it's not.
        api.build(recipe, notest=False, config=testing_config)


def test_pin_depends(testing_config):
    """purpose of 'record' argument is to put a 'requires' file that records pinned run
    dependencies
    """
    recipe = os.path.join(metadata_dir, '_pin_depends_record')
    m = api.render(recipe, config=testing_config)[0][0]
    # the recipe python is not pinned, and having pin_depends set to record
    # will not show it in record
    assert not any(re.search('python\s+[23]\.', dep) for dep in m.meta['requirements']['run'])
    output = api.build(m, config=testing_config)[0]
    requires = package_has_file(output, 'info/requires')
    assert requires
    if PY3 and hasattr(requires, 'decode'):
        requires = requires.decode()
    assert re.search('python\=[23]\.', requires), "didn't find pinned python in info/requires"


def test_failed_patch_exits_build(testing_config):
    with pytest.raises(RuntimeError):
        api.build(os.path.join(metadata_dir, '_bad_patch'), config=testing_config)


def test_version_mismatch_in_variant_does_not_infinitely_rebuild_folder(testing_config):
    # unsatisfiable; also not buildable (test_a recipe version is 2.0)
    testing_config.variant['test_a'] = "1.0"
    recipe = os.path.join(metadata_dir, '_build_deps_no_infinite_loop', 'test_b')
    with pytest.raises(DependencyNeedsBuildingError):
        api.build(recipe, config=testing_config)
    # passes now, because package can be built, or is already built.  Doesn't matter which.
    testing_config.variant['test_a'] = "2.0"
    api.build(recipe, config=testing_config)


def test_provides_features_metadata(testing_config):
    recipe = os.path.join(metadata_dir, '_requires_provides_features')
    out = api.build(recipe, config=testing_config)[0]
    index = json.loads(package_has_file(out, 'info/index.json'))
    assert 'requires_features' in index
    assert index['requires_features'] == {'test': 'ok'}
    assert 'provides_features' in index
    assert index['provides_features'] == {'test2': 'also_ok'}


@pytest.mark.skipif(not sys.platform.startswith('linux'),
                    reason="Not implemented outside linux for now")
def test_overlinking_detection(testing_config):
    testing_config.activate = True
    testing_config.error_overlinking = True
    recipe = os.path.join(metadata_dir, '_overlinkage_detection')
    dest_file = os.path.join(recipe, 'build.sh')
    copy_into(os.path.join(recipe, 'build_scripts', 'default.sh'), dest_file)
    api.build(recipe, config=testing_config)
    copy_into(os.path.join(recipe, 'build_scripts', 'no_as_needed.sh'), dest_file)
    with pytest.raises(SystemExit):
        api.build(recipe, config=testing_config)
    rm_rf(dest_file)


def test_empty_package_with_python_in_build_and_host_barfs(testing_config):
    recipe = os.path.join(metadata_dir, '_empty_pkg_with_python_build_host')
    with pytest.raises(CondaBuildException):
        api.build(recipe, config=testing_config)


def test_empty_package_with_python_and_compiler_in_build_barfs(testing_config):
    recipe = os.path.join(metadata_dir, '_compiler_python_build_section')
    with pytest.raises(CondaBuildException):
        api.build(recipe, config=testing_config)


def test_downstream_tests(testing_config):
    upstream = os.path.join(metadata_dir, '_test_downstreams/upstream')
    downstream = os.path.join(metadata_dir, '_test_downstreams/downstream')
    api.build(downstream, config=testing_config, notest=True)
    with pytest.raises(SystemExit):
        api.build(upstream, config=testing_config)


@pytest.mark.xfail(not conda_46, reason="conda 4.6 changed logger level from info to warn")
def test_warning_on_file_clobbering(testing_config, caplog):
    recipe_dir = os.path.join(metadata_dir, '_overlapping_files_warning')

    api.build(os.path.join(recipe_dir, 'a', ), config=testing_config)
    api.build(os.path.join(recipe_dir, 'b', ), config=testing_config)
    assert "Conda was asked to clobber an existing path" in caplog.text
    with pytest.raises((ClobberError, CondaMultiError)):
        with env_var('CONDA_PATH_CONFLICT', 'prevent', reset_context):
            api.build(os.path.join(recipe_dir, 'b'), config=testing_config)


@pytest.mark.serial
def test_verify_bad_package(testing_config):
    from conda_verify.errors import PackageError
    recipe_dir = os.path.join(fail_dir, 'create_bad_folder_for_conda_verify')
    api.build(recipe_dir, config=testing_config)
    with pytest.raises(PackageError):
        testing_config.exit_on_verify_error = True
        api.build(recipe_dir, config=testing_config)
    # ignore the error that we know should be raised, and re-run to make sure it is actually ignored
    testing_config.ignore_verify_codes = ['C1125', 'C1115']
    api.build(recipe_dir, config=testing_config)
