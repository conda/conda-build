import os
import stat
import sys
import unittest
import zipfile

import pytest

import conda_build.utils as utils


def makefile(name, contents=""):
    name = os.path.abspath(name)
    path = os.path.dirname(name)

    if not os.path.exists(path):
        os.makedirs(path)

    with open(name, 'w') as f:
        f.write(contents)


@pytest.mark.skipif(utils.on_win, reason="only unix has python version in site-packages path")
def test_get_site_packages():
    # https://github.com/conda/conda-build/issues/1055#issuecomment-250961576
    # crazy unreal python version that should show up in a second
    crazy_path = os.path.join('/dummy', 'lib', 'python8.2', 'site-packages')
    site_packages = utils.get_site_packages('/dummy', '8.2')
    assert site_packages == crazy_path


def test_prepend_sys_path():
    path = sys.path[:]
    with utils.sys_path_prepended(sys.prefix):
        assert sys.path != path
        assert sys.path[1].startswith(sys.prefix)


def test_copy_source_tree(namespace_setup):
    dst = os.path.join(namespace_setup, 'dest')
    utils.copy_into(os.path.join(namespace_setup, 'namespace'), dst)
    assert os.path.isfile(os.path.join(dst, 'package', 'module.py'))


def test_merge_namespace_trees(namespace_setup):
    dep = os.path.join(namespace_setup, 'other_tree', 'namespace', 'package', 'dependency.py')
    makefile(dep)

    utils.copy_into(os.path.join(namespace_setup, 'other_tree'), namespace_setup)
    assert os.path.isfile(os.path.join(namespace_setup, 'namespace', 'package',
                                                'module.py'))
    assert os.path.isfile(dep)


@pytest.fixture(scope='function')
def namespace_setup(testing_workdir, request):
    namespace = os.path.join(testing_workdir, 'namespace')
    package = os.path.join(namespace, 'package')
    makefile(os.path.join(package, "module.py"))
    return testing_workdir


def test_disallow_merge_conflicts(namespace_setup, testing_config):
    duplicate = os.path.join(namespace_setup, 'dupe', 'namespace', 'package', 'module.py')
    makefile(duplicate)
    with pytest.raises(IOError):
        utils.merge_tree(os.path.dirname(duplicate), os.path.join(namespace_setup, 'namespace',
                                                 'package'))


@pytest.mark.skipif(utils.on_win, reason="only unix has full os.chmod capabilities")
def test_unzip(testing_workdir):
    with open('file_with_execute_permission', 'w') as f:
        f.write("test")
    file_path = os.path.join(testing_workdir, 'file_with_execute_permission')
    current_permissions = os.stat(file_path).st_mode
    os.chmod(file_path, current_permissions | stat.S_IXUSR)
    with zipfile.ZipFile('test.zip', 'w') as z:
        z.write('file_with_execute_permission')
    utils.unzip('test.zip', 'unpack')
    unpacked_path = os.path.join('unpack', 'file_with_execute_permission')
    assert os.path.isfile(unpacked_path)
    st_mode = os.stat(unpacked_path).st_mode
    assert st_mode & stat.S_IXUSR


def test_disallow_in_tree_merge(testing_workdir):
    with open('testfile', 'w') as f:
        f.write("test")
    with pytest.raises(AssertionError):
        utils.merge_tree(testing_workdir, os.path.join(testing_workdir, 'subdir'))


class TestUtils(unittest.TestCase):

    def test_relative_default(self):
        for f, r in [
                ('bin/python', '../lib'),
                ('lib/libhdf5.so', '.'),
                ('lib/python2.6/foobar.so', '..'),
                ('lib/python2.6/lib-dynload/zlib.so', '../..'),
                ('lib/python2.6/site-packages/pyodbc.so', '../..'),
                ('lib/python2.6/site-packages/bsdiff4/core.so', '../../..'),
                ('xyz', './lib'),
                ('bin/somedir/cmd', '../../lib'),
        ]:
            self.assertEqual(utils.relative(f), r)

    def test_relative_lib(self):
        for f, r in [
                ('bin/python', '../lib'),
                ('lib/libhdf5.so', '.'),
                ('lib/python2.6/foobar.so', '..'),
                ('lib/python2.6/lib-dynload/zlib.so', '../..'),
                ('lib/python2.6/site-packages/pyodbc.so', '../..'),
                ('lib/python2.6/site-packages/bsdiff3/core.so', '../../..'),
                ('xyz', './lib'),
                ('bin/somedir/cmd', '../../lib'),
                ('bin/somedir/somedir2/cmd', '../../../lib'),
        ]:
            self.assertEqual(utils.relative(f, 'lib'), r)

    def test_relative_subdir(self):
        for f, r in [
                ('lib/libhdf5.so', './sub'),
                ('lib/sub/libhdf5.so', '.'),
                ('bin/python', '../lib/sub'),
                ('bin/somedir/cmd', '../../lib/sub'),
        ]:
            self.assertEqual(utils.relative(f, 'lib/sub'), r)

    def test_relative_prefix(self):
        for f, r in [
                ('xyz', '.'),
                ('a/xyz', '..'),
                ('a/b/xyz', '../..'),
                ('a/b/c/xyz', '../../..'),
                ('a/b/c/d/xyz', '../../../..'),
        ]:
            self.assertEqual(utils.relative(f, '.'), r)

    def test_relative_2(self):
        for f, r in [
                ('a/b/c/d/libhdf5.so', '../..'),
                ('a/b/c/libhdf5.so', '..'),
                ('a/b/libhdf5.so', '.'),
                ('a/libhdf5.so', './b'),
                ('x/x/libhdf5.so', '../../a/b'),
                ('x/b/libhdf5.so', '../../a/b'),
                ('x/libhdf5.so', '../a/b'),
                ('libhdf5.so', './a/b'),
        ]:
            self.assertEqual(utils.relative(f, 'a/b'), r)

    def test_relative_3(self):
        for f, r in [
                ('a/b/c/d/libhdf5.so', '..'),
                ('a/b/c/libhdf5.so', '.'),
                ('a/b/libhdf5.so', './c'),
                ('a/libhdf5.so', './b/c'),
                ('libhdf5.so', './a/b/c'),
                ('a/b/x/libhdf5.so', '../c'),
                ('a/x/x/libhdf5.so', '../../b/c'),
                ('x/x/x/libhdf5.so', '../../../a/b/c'),
                ('x/x/libhdf5.so', '../../a/b/c'),
                ('x/libhdf5.so', '../a/b/c'),
        ]:
            self.assertEqual(utils.relative(f, 'a/b/c'), r)

    def test_relative_4(self):
        for f, r in [
                ('a/b/c/d/libhdf5.so', '.'),
                ('a/b/c/x/libhdf5.so', '../d'),
                ('a/b/x/x/libhdf5.so', '../../c/d'),
                ('a/x/x/x/libhdf5.so', '../../../b/c/d'),
                ('x/x/x/x/libhdf5.so', '../../../../a/b/c/d'),
        ]:
            self.assertEqual(utils.relative(f, 'a/b/c/d'), r)


def test_expand_globs(testing_workdir):
    files = ['abc', 'acb']
    for f in files:
        with open(f, 'w') as _f:
            _f.write('weee')
    assert utils.expand_globs(files, testing_workdir) == files
    assert utils.expand_globs(['a*'], testing_workdir) == files


def test_filter_files():
    # Files that should be filtered out.
    files_list = ['.git/a', 'something/.git/a', '.git\\a', 'something\\.git\\a']
    assert not utils.filter_files(files_list, '')

    # Files that should *not* be filtered out.
    # Example of valid 'x.git' directory:
    #    lib/python3.4/site-packages/craftr/stl/craftr.utils.git/Craftrfile
    files_list = ['a', 'x.git/a', 'something/x.git/a',
                  'x.git\\a', 'something\\x.git\\a']
    assert len(utils.filter_files(files_list, '')) == len(files_list)
