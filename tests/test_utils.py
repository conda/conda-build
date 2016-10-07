import unittest
import os
import sys

import pytest

import conda_build.utils as utils
from .utils import test_config, testing_workdir


def makefile(name, contents=""):
    name = os.path.abspath(name)
    path = os.path.dirname(name)

    if not os.path.exists(path):
        os.makedirs(path)

    with open(name, 'w') as f:
        f.write(contents)



@pytest.fixture(scope='function')
def namespace_setup(testing_workdir, request):
    namespace = os.path.join(testing_workdir, 'namespace')
    package = os.path.join(namespace, 'package')
    makefile(os.path.join(package, "module.py"))
    return testing_workdir


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


def test_disallow_merge_conflicts(namespace_setup, test_config):
    duplicate = os.path.join(namespace_setup, 'dupe', 'namespace', 'package', 'module.py')
    makefile(duplicate)
    with pytest.raises(IOError):
        utils.merge_tree(os.path.dirname(duplicate), os.path.join(namespace_setup, 'namespace',
                                                 'package'))


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
