import os
import shutil
import sys

import pytest

from conda_build import post, api
from conda_build.utils import on_win, package_has_file, get_site_packages

from .utils import add_mangling, metadata_dir


def test_compile_missing_pyc(testing_workdir):
    good_files = ['f1.py', 'f3.py']
    bad_file = 'f2_bad.py'
    tmp = os.path.join(testing_workdir, 'tmp')
    shutil.copytree(os.path.join(os.path.dirname(__file__), 'test-recipes',
                                 'metadata', '_compile-test'), tmp)
    post.compile_missing_pyc(os.listdir(tmp), cwd=tmp,
                                python_exe=sys.executable)
    for f in good_files:
        assert os.path.isfile(os.path.join(tmp, add_mangling(f)))
    assert not os.path.isfile(os.path.join(tmp, add_mangling(bad_file)))


@pytest.mark.skipif(on_win, reason="no linking on win")
def test_hardlinks_to_copies(testing_workdir):
    with open('test1', 'w') as f:
        f.write("\n")

    os.link('test1', 'test2')
    assert os.lstat('test1').st_nlink == 2
    assert os.lstat('test2').st_nlink == 2

    post.make_hardlink_copy('test1', os.getcwd())
    post.make_hardlink_copy('test2', os.getcwd())

    assert os.lstat('test1').st_nlink == 1
    assert os.lstat('test2').st_nlink == 1


def test_postbuild_files_raise(testing_metadata, testing_workdir):
    fn = 'buildstr', 'buildnum', 'version'
    for f in fn:
        with open(os.path.join(testing_metadata.config.work_dir,
                               f'__conda_{f}__.txt'), 'w') as fh:
            fh.write('123')
        with pytest.raises(ValueError, match=f):
            post.get_build_metadata(testing_metadata)


@pytest.mark.skipif(on_win, reason="fix_shebang is not executed on win32")
def test_fix_shebang(testing_config):
    fname = 'test1'
    with open(fname, 'w') as f:
        f.write("\n")
    os.chmod(fname, 0o000)
    post.fix_shebang(fname, '.', '/test/python')
    assert os.stat(fname).st_mode == 33277  # file with permissions 0o775


def test_postlink_script_in_output_explicit(testing_config):
    recipe = os.path.join(metadata_dir, '_post_link_in_output')
    pkg = api.build(recipe, config=testing_config, notest=True)[0]
    assert (package_has_file(pkg, 'bin/.out1-post-link.sh') or
            package_has_file(pkg, 'Scripts/.out1-post-link.bat'))


def test_postlink_script_in_output_implicit(testing_config):
    recipe = os.path.join(metadata_dir, '_post_link_in_output_implicit')
    pkg = api.build(recipe, config=testing_config, notest=True)[0]
    assert (package_has_file(pkg, 'bin/.out1-post-link.sh') or
            package_has_file(pkg, 'Scripts/.out1-post-link.bat'))


def test_pypi_installer_metadata(testing_config):
    recipe = os.path.join(metadata_dir, '_pypi_installer_metadata')
    pkg = api.build(recipe, config=testing_config, notest=True)[0]
    expected_installer = '{}/imagesize-1.1.0.dist-info/INSTALLER'.format(get_site_packages('', '3.9'))
    assert 'conda' == (package_has_file(pkg, expected_installer, refresh_mode='forced'))
