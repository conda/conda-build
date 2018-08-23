# For the most part, all functionality should be tested with the api tests,
#   because they actually provide coverage.  These tests are here to make
#   sure that the CLI still works.

from glob import glob
import json
import os
import re
import sys
import yaml

import pytest

from conda_build.conda_interface import download, reset_context
from conda_build.tarcheck import TarCheck

from conda_build import api
from conda_build.utils import (get_site_packages, on_win, get_build_folders, package_has_file,
                               check_call_env, tar_xf)
from conda_build.conda_interface import TemporaryDirectory, conda_43
import conda_build
from .utils import metadata_dir, put_bad_conda_on_path

import conda_build.cli.main_build as main_build
import conda_build.cli.main_render as main_render
import conda_build.cli.main_convert as main_convert
import conda_build.cli.main_develop as main_develop
import conda_build.cli.main_metapackage as main_metapackage
import conda_build.cli.main_skeleton as main_skeleton
import conda_build.cli.main_inspect as main_inspect
import conda_build.cli.main_index as main_index


def test_build():
    args = ['--no-anaconda-upload', os.path.join(metadata_dir, "empty_sections"), '--no-activate',
            '--no-anaconda-upload']
    main_build.execute(args)


# regression test for https://github.com/conda/conda-build/issues/1450
def test_build_with_conda_not_on_path(testing_workdir):
    with put_bad_conda_on_path(testing_workdir):
        # using subprocess is not ideal, but it is the easiest way to ensure that PATH
        #    is altered the way we want here.
        check_call_env('conda-build {0} --no-anaconda-upload'.format(
            os.path.join(metadata_dir, "python_run")).split(),
                       env=os.environ)


def test_build_add_channel():
    """This recipe requires the conda_build_test_requirement package, which is
    only on the conda_build_test channel. This verifies that the -c argument
    works."""

    args = ['-c', 'conda_build_test', '--no-activate', '--no-anaconda-upload',
            os.path.join(metadata_dir, "_recipe_requiring_external_channel")]
    main_build.execute(args)


@pytest.mark.xfail
def test_build_without_channel_fails(testing_workdir):
    # remove the conda forge channel from the arguments and make sure that we fail.  If we don't,
    #    we probably have channels in condarc, and this is not a good test.
    args = ['--no-anaconda-upload', '--no-activate',
            os.path.join(metadata_dir, "_recipe_requiring_external_channel")]
    main_build.execute(args)


def test_render_add_channel():
    """This recipe requires the conda_build_test_requirement package, which is
    only on the conda_build_test channel. This verifies that the -c argument
    works for rendering."""
    with TemporaryDirectory() as tmpdir:
        rendered_filename = os.path.join(tmpdir, 'out.yaml')
        args = ['-c', 'conda_build_test', os.path.join(metadata_dir,
                            "_recipe_requiring_external_channel"), '--file', rendered_filename]
        main_render.execute(args)
        rendered_meta = yaml.safe_load(open(rendered_filename, 'r'))
        required_package_string = [pkg for pkg in rendered_meta['requirements']['build'] if
                                   'conda_build_test_requirement' in pkg][0]
        required_package_details = required_package_string.split(' ')
        assert len(required_package_details) > 1, ("Expected version number on successful "
                                    "rendering, but got only {}".format(required_package_details))
        assert required_package_details[1] == '1.0', "Expected version number 1.0 on successful rendering, but got {}".format(required_package_details[1])


def test_render_without_channel_fails():
    # do make extra channel available, so the required package should not be found
    with TemporaryDirectory() as tmpdir:
        rendered_filename = os.path.join(tmpdir, 'out.yaml')
        args = ['--override-channels', os.path.join(metadata_dir, "_recipe_requiring_external_channel"), '--file', rendered_filename]
        main_render.execute(args)
        rendered_meta = yaml.safe_load(open(rendered_filename, 'r'))
        required_package_string = [pkg for pkg in
                                   rendered_meta.get('requirements', {}).get('build', [])
                                   if 'conda_build_test_requirement' in pkg][0]
        assert required_package_string == 'conda_build_test_requirement', \
               "Expected to get only base package name because it should not be found, but got :{}".format(required_package_string)


def test_no_filename_hash(testing_workdir, testing_metadata, capfd):
    api.output_yaml(testing_metadata, 'meta.yaml')
    args = ['--output', testing_workdir, '--old-build-string']
    main_render.execute(args)
    output, error = capfd.readouterr()
    assert not re.search('h[0-9a-f]{%d}' % testing_metadata.config.hash_length, output)

    args = ['--no-anaconda-upload', '--no-activate', testing_workdir, '--old-build-string']
    main_build.execute(args)
    output, error = capfd.readouterr()
    assert not re.search('test_no_filename_hash.*h[0-9a-f]{%d}' % testing_metadata.config.hash_length, output)
    assert not re.search('test_no_filename_hash.*h[0-9a-f]{%d}' % testing_metadata.config.hash_length, error)


def test_render_output_build_path(testing_workdir, testing_metadata, capfd, caplog):
    api.output_yaml(testing_metadata, 'meta.yaml')
    args = ['--output', os.path.join(testing_workdir)]
    main_render.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", testing_metadata.config.host_subdir,
                             "test_render_output_build_path-1.0-1.tar.bz2")
    output, error = capfd.readouterr()
    assert output.rstrip() == test_path, error
    assert error == ""


def test_build_output_build_path(testing_workdir, testing_metadata, testing_config, capfd):
    api.output_yaml(testing_metadata, 'meta.yaml')
    testing_config.verbose = False
    testing_config.debug = False
    args = ['--output', os.path.join(testing_workdir)]
    main_build.execute(args)
    test_path = os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir,
                                  "test_build_output_build_path-1.0-1.tar.bz2")
    output, error = capfd.readouterr()
    assert test_path == output.rstrip(), error
    assert error == ""


def test_build_output_build_path_multiple_recipes(testing_workdir, testing_metadata,
                                                  testing_config, capfd):
    api.output_yaml(testing_metadata, 'meta.yaml')
    testing_config.verbose = False
    skip_recipe = os.path.join(metadata_dir, "build_skip")
    args = ['--output', testing_workdir, skip_recipe]

    main_build.execute(args)

    test_path = lambda pkg: os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir, pkg)
    test_paths = [test_path("test_build_output_build_path_multiple_recipes-1.0-1.tar.bz2"), ]

    output, error = capfd.readouterr()
    # assert error == ""
    assert output.rstrip().splitlines() == test_paths, error


def test_slash_in_recipe_arg_keeps_build_id(testing_workdir, testing_config):
    args = [os.path.join(metadata_dir, "has_prefix_files"), '--croot', testing_config.croot,
            '--no-anaconda-upload']
    outputs = main_build.execute(args)
    data = package_has_file(outputs[0], 'binary-has-prefix')
    assert data
    if hasattr(data, 'decode'):
        data = data.decode('UTF-8')
    assert 'conda-build-test-has-prefix-files_1' in data


@pytest.mark.skipif(on_win, reason="prefix is always short on win.")
def test_build_long_test_prefix_default_enabled(mocker, testing_workdir):
    recipe_path = os.path.join(metadata_dir, '_test_long_test_prefix')
    args = [recipe_path, '--no-anaconda-upload']
    main_build.execute(args)

    args.append('--no-long-test-prefix')
    with pytest.raises(SystemExit):
        main_build.execute(args)


def test_build_no_build_id(testing_workdir, testing_config):
    args = [os.path.join(metadata_dir, "has_prefix_files"), '--no-build-id',
            '--croot', testing_config.croot, '--no-activate', '--no-anaconda-upload']
    outputs = main_build.execute(args)
    data = package_has_file(outputs[0], 'binary-has-prefix')
    assert data
    if hasattr(data, 'decode'):
        data = data.decode('UTF-8')
    assert 'has_prefix_files_1' not in data


def test_build_multiple_recipes(testing_metadata, testing_workdir, testing_config):
    """Test that building two recipes in one CLI call separates the build environment for each"""
    os.makedirs('recipe1')
    os.makedirs('recipe2')
    api.output_yaml(testing_metadata, 'recipe1/meta.yaml')
    with open('recipe1/run_test.py', 'w') as f:
        f.write("import os; assert 'test_build_multiple_recipes' in os.getenv('PREFIX')")
    testing_metadata.meta['package']['name'] = 'package2'
    api.output_yaml(testing_metadata, 'recipe2/meta.yaml')
    with open('recipe2/run_test.py', 'w') as f:
        f.write("import os; assert 'package2' in os.getenv('PREFIX')")
    args = ['--no-anaconda-upload', 'recipe1', 'recipe2']
    main_build.execute(args)


def test_build_output_folder(testing_workdir, testing_metadata, capfd):
    api.output_yaml(testing_metadata, 'meta.yaml')
    with TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out')
        args = [testing_workdir, '--no-build-id',
                '--croot', tmp, '--no-activate', '--no-anaconda-upload',
                '--output-folder', out]
        output = main_build.execute(args)[0]
        assert os.path.isfile(os.path.join(out, testing_metadata.config.host_subdir,
                                           os.path.basename(output)))


def test_build_source(testing_workdir):
    with TemporaryDirectory() as tmp:
        args = [os.path.join(metadata_dir, '_pyyaml_find_header'), '--source', '--no-build-id',
                '--croot', tmp, '--no-activate', '--no-anaconda-upload', ]
        main_build.execute(args)
        assert os.path.isfile(os.path.join(tmp, 'work', 'setup.py'))


def test_render_output_build_path_set_python(testing_workdir, testing_metadata, capfd):
    testing_metadata.meta['requirements'] = {'host': ['python'],
                                             'run': ['python']}
    api.output_yaml(testing_metadata, 'meta.yaml')
    # build the other major thing, whatever it is
    if sys.version_info.major == 3:
        version = "2.7"
    else:
        version = "3.5"

    api.output_yaml(testing_metadata, 'meta.yaml')
    metadata = api.render(testing_workdir, python=version)[0][0]

    args = ['--output', testing_workdir, '--python', version]
    main_render.execute(args)

    _hash = metadata.hash_dependencies()
    test_path = "test_render_output_build_path_set_python-1.0-py{}{}{}_1.tar.bz2".format(
                                      version.split('.')[0], version.split('.')[1], _hash)
    output, error = capfd.readouterr()
    assert os.path.basename(output.rstrip()) == test_path, error


def test_skeleton_pypi(testing_workdir, testing_config):
    args = ['pypi', 'click']
    main_skeleton.execute(args)
    assert os.path.isdir('click')

    # ensure that recipe generated is buildable
    args = ['click', '--no-anaconda-upload', '--no-activate']
    main_build.execute(args)
    # output, error = capfd.readouterr()
    # if hasattr(output, 'decode'):
    #     output = output.decode()
    # assert 'Nothing to test for' not in output
    # assert 'Nothing to test for' not in error


def test_skeleton_pypi_arguments_work(testing_workdir):
    """
    These checks whether skeleton executes without error when these
    options are specified on the command line AND whether the underlying
    functionality works as a regression test for:

    https://github.com/conda/conda-build/pull/1384
    """
    args = ['pypi', 'msumastro', '--pin-numpy']
    main_skeleton.execute(args)
    assert os.path.isdir('msumastro')

    # Deliberately bypass metadata reading in conda build to get as
    # close to the "ground truth" as possible.
    with open(os.path.join('msumastro', 'meta.yaml')) as f:
        assert f.read().count('numpy x.x') == 2

    args = ['pypi', 'photutils', '--version=0.2.2', '--setup-options=--offline']
    main_skeleton.execute(args)
    assert os.path.isdir('photutils')
    # Check that the setup option occurs in bld.bat and build.sh.

    m = api.render('photutils')[0][0]
    assert '--offline' in m.meta['build']['script']
    assert m.version() == '0.2.2'


def test_metapackage(testing_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ['metapackage_test', '1.0', '-d', 'bzip2', '--no-anaconda-upload']
    main_metapackage.execute(args)
    test_path = glob(os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir,
                             'metapackage_test-1.0-0.tar.bz2'))[0]
    assert os.path.isfile(test_path)


def test_metapackage_build_number(testing_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ['metapackage_test_build_number', '1.0', '-d', 'bzip2', '--build-number', '1',
            '--no-anaconda-upload']
    main_metapackage.execute(args)
    test_path = glob(os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir,
                             'metapackage_test_build_number-1.0-1.tar.bz2'))[0]
    assert os.path.isfile(test_path)


def test_metapackage_build_string(testing_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ['metapackage_test_build_string', '1.0', '-d', 'bzip2', '--build-string', 'frank',
            '--no-anaconda-upload']
    main_metapackage.execute(args)
    test_path = glob(os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir,
                             'metapackage_test_build_string-1.0-frank*.tar.bz2'))[0]
    assert os.path.isfile(test_path)


def test_metapackage_metadata(testing_config, testing_workdir):
    args = ['metapackage_testing_metadata', '1.0', '-d', 'bzip2', "--home", "http://abc.com",
            "--summary", "wee", "--license", "BSD", '--no-anaconda-upload']
    main_metapackage.execute(args)

    test_path = glob(os.path.join(sys.prefix, "conda-bld", testing_config.host_subdir,
                             'metapackage_testing_metadata-1.0-0.tar.bz2'))[0]
    assert os.path.isfile(test_path)
    info = json.loads(package_has_file(test_path, 'info/index.json').decode('utf-8'))
    assert info['license'] == 'BSD'
    info = json.loads(package_has_file(test_path, 'info/about.json').decode('utf-8'))
    assert info['home'] == 'http://abc.com'
    assert info['summary'] == 'wee'


def testing_index(testing_workdir):
    args = ['.']
    main_index.execute(args)
    assert os.path.isfile('noarch/repodata.json')


def test_inspect_installable(testing_workdir):
    args = ['channels', '--test-installable', 'conda-team']
    main_inspect.execute(args)


def test_inspect_linkages(testing_workdir, capfd):
    # get a package that has known object output
    args = ['linkages', 'python']
    if sys.platform == 'win32':
        with pytest.raises(SystemExit) as exc:
            main_inspect.execute(args)
            assert 'conda inspect linkages is only implemented in Linux and OS X' in exc
    else:
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert 'libncursesw' in output


def test_inspect_objects(testing_workdir, capfd):
    # get a package that has known object output
    args = ['objects', 'python']
    if sys.platform != 'darwin':
        with pytest.raises(SystemExit) as exc:
            main_inspect.execute(args)
            assert 'conda inspect objects is only implemented in OS X' in exc
    else:
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert re.search('rpath:.*@loader_path', output)


@pytest.mark.skipif(on_win, reason="Windows prefix length doesn't matter (yet?)")
def test_inspect_prefix_length(testing_workdir, capfd):
    from conda_build import api
    # build our own known-length package here
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    config.prefix_length = 80
    outputs = api.build(recipe_path, config=config, notest=True)

    args = ['prefix-lengths'] + outputs
    with pytest.raises(SystemExit):
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert 'Packages with binary prefixes shorter than' in output
        assert all(fn in output for fn in outputs)

    config.prefix_length = 255
    # reset the build id so that a new one is computed
    config._build_id = ""
    api.build(recipe_path, config=config, notest=True)
    main_inspect.execute(args)
    output, error = capfd.readouterr()
    assert 'No packages found with binary prefixes shorter' in output


def test_inspect_hash_input(testing_metadata, testing_workdir, capfd):
    testing_metadata.meta['requirements']['build'] = ['zlib']
    api.output_yaml(testing_metadata, 'meta.yaml')
    output = api.build(testing_workdir, notest=True)[0]
    with open(os.path.join(testing_workdir, 'conda_build_config.yaml'), 'w') as f:
        yaml.dump({'zlib': ['1.2.11']}, f)
    args = ['hash-inputs', output]
    main_inspect.execute(args)
    output, error = capfd.readouterr()
    assert 'zlib' in output


@pytest.mark.xfail(conda_43, reason="develop broke with old conda.  We don't really care.")
def test_develop(testing_env):
    f = "https://pypi.io/packages/source/c/conda_version_test/conda_version_test-0.1.0-1.tar.gz"
    download(f, "conda_version_test.tar.gz")
    tar_xf("conda_version_test.tar.gz", testing_env)
    extract_folder = 'conda_version_test-0.1.0-1'
    cwd = os.getcwd()
    args = ['-p', testing_env, extract_folder]
    main_develop.execute(args)
    py_ver = '.'.join((str(sys.version_info.major), str(sys.version_info.minor)))
    assert cwd in open(os.path.join(get_site_packages(testing_env, py_ver), 'conda.pth')).read()
    args = ['--uninstall', '-p', testing_env, extract_folder]
    main_develop.execute(args)
    assert (cwd not in open(os.path.join(get_site_packages(testing_env, py_ver),
                                         'conda.pth')).read())


def test_convert(testing_workdir, testing_config):
    # download a sample py2.7 package
    f = 'https://repo.continuum.io/pkgs/free/win-64/affine-2.0.0-py27_0.tar.bz2'
    pkg_name = "affine-2.0.0-py27_0.tar.bz2"
    download(f, pkg_name)
    # convert it to all platforms
    args = ['-o', 'converted', '--platform', 'all', pkg_name]
    main_convert.execute(args)
    platforms = ['osx-64', 'win-32', 'linux-64', 'linux-32']
    for platform in platforms:
        dirname = os.path.join('converted', platform)
        if platform != 'win-64':
            assert os.path.isdir(dirname)
            assert pkg_name in os.listdir(dirname)
            testing_config.host_subdir = platform
            with TarCheck(os.path.join(dirname, pkg_name), config=testing_config) as tar:
                tar.correct_subdir()
        else:
            assert not os.path.isdir(dirname)


@pytest.mark.serial
def test_purge(testing_workdir, testing_metadata):
    """
    purge clears out build folders - things like some_pkg_12048309850135

    It does not clear out build packages from folders like osx-64 or linux-64.
    """
    api.output_yaml(testing_metadata, 'meta.yaml')
    outputs = api.build(testing_workdir, notest=True)
    args = ['purge']
    main_build.execute(args)
    dirs = get_build_folders(testing_metadata.config.croot)
    assert not dirs
    # make sure artifacts are kept - only temporary folders get nuked
    assert all(os.path.isfile(fn) for fn in outputs)


@pytest.mark.serial
def test_purge_all(testing_workdir, testing_metadata):
    """
    purge-all clears out build folders as well as build packages in the osx-64 folders and such
    """
    api.output_yaml(testing_metadata, 'meta.yaml')
    with TemporaryDirectory() as tmpdir:
        testing_metadata.config.croot = tmpdir
        outputs = api.build(testing_workdir, config=testing_metadata.config, notest=True)
        args = ['purge-all', '--croot', tmpdir]
        main_build.execute(args)
        assert not get_build_folders(testing_metadata.config.croot)
        assert not any(os.path.isfile(fn) for fn in outputs)


def test_no_force_upload(mocker, testing_workdir, testing_metadata):
    with open(os.path.join(testing_workdir, '.condarc'), 'w') as f:
        f.write('anaconda_upload: True\n')
        f.write('conda_build:\n')
        f.write('    force_upload: False\n')
    del testing_metadata.meta['test']
    api.output_yaml(testing_metadata, 'meta.yaml')
    args = ['--no-force-upload', testing_workdir]
    call = mocker.patch.object(conda_build.build.subprocess, 'call')
    reset_context(testing_workdir)
    main_build.execute(args)
    pkg = api.get_output_file_path(testing_metadata)
    assert call.called_once_with(['anaconda', 'upload', pkg])
    args = [testing_workdir]
    with open(os.path.join(testing_workdir, '.condarc'), 'w') as f:
        f.write('anaconda_upload: True\n')
    main_build.execute(args)
    assert call.called_once_with(['anaconda', 'upload', '--force', pkg])


def test_conda_py_no_period(testing_workdir, testing_metadata, monkeypatch):
    monkeypatch.setenv('CONDA_PY', '34')
    testing_metadata.meta['requirements'] = {'host': ['python'],
                                             'run': ['python']}
    api.output_yaml(testing_metadata, 'meta.yaml')
    outputs = api.build(testing_workdir, notest=True)
    assert any('py34' in output for output in outputs)


def test_build_skip_existing(testing_workdir, capfd, mocker):
    # build the recipe first
    empty_sections = os.path.join(metadata_dir, "empty_sections")
    args = ['--no-anaconda-upload', empty_sections]
    main_build.execute(args)
    args.insert(0, '--skip-existing')
    import conda_build.source
    provide = mocker.patch.object(conda_build.source, 'provide')
    main_build.execute(args)
    provide.assert_not_called()
    output, error = capfd.readouterr()
    assert ("are already built" in output or "are already built" in error)


def test_build_skip_existing_croot(testing_workdir, capfd):
    # build the recipe first
    empty_sections = os.path.join(metadata_dir, "empty_sections")
    args = ['--no-anaconda-upload', '--croot', testing_workdir, empty_sections]
    main_build.execute(args)
    args.insert(0, '--skip-existing')
    main_build.execute(args)
    output, error = capfd.readouterr()
    assert "are already built" in output


def test_package_test(testing_workdir, testing_metadata):
    """Test calling conda build -t <package file> - rather than <recipe dir>"""
    api.output_yaml(testing_metadata, 'recipe/meta.yaml')
    output = api.build(testing_workdir, config=testing_metadata.config, notest=True)[0]
    args = ['-t', output]
    main_build.execute(args)


def test_activate_scripts_not_included(testing_workdir):
    recipe = os.path.join(metadata_dir, '_activate_scripts_not_included')
    args = ['--no-anaconda-upload', '--croot', testing_workdir, recipe]
    main_build.execute(args)
    out = api.get_output_file_paths(recipe, croot=testing_workdir)[0]
    for f in ('bin/activate', 'bin/deactivate', 'bin/conda',
              'Scripts/activate.bat', 'Scripts/deactivate.bat', 'Scripts/conda.bat',
              'Scripts/activate.exe', 'Scripts/deactivate.exe', 'Scripts/conda.exe',
              'Scripts/activate', 'Scripts/deactivate', 'Scripts/conda'):
        assert not package_has_file(out, f)


def test_relative_path_croot():
    # this tries to build a package while specifying the croot with a relative path:
    # conda-build --no-test --croot ./relative/path

    empty_sections = os.path.join(metadata_dir, "empty_with_build_script")
    croot_rel = os.path.join('.', 'relative', 'path')
    args = ['--no-anaconda-upload', '--croot', croot_rel, empty_sections]
    outputfile = main_build.execute(args)

    assert len(outputfile) == 1
    assert os.path.isfile(outputfile[0])


def test_relative_path_test_artifact():
    # this test builds a package into (cwd)/relative/path and then calls:
    # conda-build --test ./relative/path/{platform}/{artifact}.tar.bz2

    empty_sections = os.path.join(metadata_dir, "empty_with_build_script")
    croot_rel = os.path.join('.', 'relative', 'path')
    croot_abs = os.path.abspath(os.path.normpath(croot_rel))

    # build the package
    args = ['--no-anaconda-upload', '--no-test', '--croot', croot_abs, empty_sections]
    output_file_abs = main_build.execute(args)
    assert(len(output_file_abs) == 1)

    output_file_rel = os.path.join(croot_rel, os.path.relpath(output_file_abs[0], croot_abs))

    # run the test stage with relative path
    args = ['--no-anaconda-upload', '--test', output_file_rel]
    main_build.execute(args)


def test_relative_path_test_recipe():
    # this test builds a package into (cwd)/relative/path and then calls:
    # conda-build --test --croot ./relative/path/ /abs/path/to/recipe

    empty_sections = os.path.join(metadata_dir, "empty_with_build_script")
    croot_rel = os.path.join('.', 'relative', 'path')
    croot_abs = os.path.abspath(os.path.normpath(croot_rel))

    # build the package
    args = ['--no-anaconda-upload', '--no-test', '--croot', croot_abs, empty_sections]
    output_file_abs = main_build.execute(args)
    assert(len(output_file_abs) == 1)

    # run the test stage with relative croot
    args = ['--no-anaconda-upload', '--test', '--croot', croot_rel, empty_sections]
    main_build.execute(args)


def test_render_with_python_arg_reduces_subspace(capfd):
    recipe = os.path.join(metadata_dir, "..", "variants", "20_subspace_selection_cli")
    # build the package
    args = [recipe, '--python=2.7', '--output']
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert(len(out.splitlines()) == 2)

    args = [recipe, '--python=3.5', '--output']
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert(len(out.splitlines()) == 1)

    # should raise an error, because python 3.6 is not in the matrix, so we don't know which vc
    # to associate with
    args = [recipe, '--python=3.6', '--output']
    with pytest.raises(ValueError):
        main_render.execute(args)


def test_test_extra_dep(testing_metadata):
    testing_metadata.meta['test']['imports'] = ['click']
    api.output_yaml(testing_metadata, 'meta.yaml')
    output = api.build(testing_metadata, notest=True, anaconda_upload=False)[0]

    # tests version constraints.  CLI would quote this - "click <6.7"
    args = [output, '-t', '--extra-deps', 'click <6.7']
    # extra_deps will add it in
    main_build.execute(args)

    # missing click dep will fail tests
    with pytest.raises(SystemExit):
        args = [output, '-t']
        # extra_deps will add it in
        main_build.execute(args)
