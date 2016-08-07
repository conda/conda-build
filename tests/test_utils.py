import unittest
import tempfile
import shutil
import os

import conda_build.utils as utils
from .utils import test_config


class TestCopyInto(unittest.TestCase):

    def setUp(self):
        self.src = tempfile.mkdtemp()
        self.dst = tempfile.mkdtemp()

        self.namespace = os.path.join(self.src, 'namespace')
        self.package = os.path.join(self.namespace, 'package')
        self.module = os.path.join(self.package, 'module.py')

        os.makedirs(self.namespace)
        os.makedirs(self.package)
        self.makefile(self.module)

    def makefile(self, name, contents=''):

        name = os.path.abspath(name)
        path = os.path.dirname(name)

        if not os.path.exists(path):
            os.makedirs(path)

        with open(name, 'w') as f:
            f.write(contents)

    def test_copy_source_tree(self, test_config):
        utils.copy_into(self.src, self.dst, test_config)
        self.assertTrue(os.path.isfile(os.path.join(self.dst, 'namespace', 'package',
                                                    'module.py')))

    def test_merge_namespace_trees(self, test_config):

        dep = os.path.join(self.dst, 'namespace', 'package', 'dependency.py')
        self.makefile(dep)

        utils.copy_into(self.src, self.dst, test_config)
        self.assertTrue(os.path.isfile(os.path.join(self.dst, 'namespace', 'package',
                                                    'module.py')))
        self.assertTrue(os.path.isfile(dep))

    def test_disallow_merge_conflicts(self, test_config):

        duplicate = os.path.join(self.dst, 'namespace', 'package', 'module.py')
        self.makefile(duplicate)
        self.assertRaises(IOError, utils.copy_into, self.src, self.dst, test_config)

    def tearDown(self):
        shutil.rmtree(self.dst)
        shutil.rmtree(self.src)


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
