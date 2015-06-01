import unittest

import conda_build.utils as utils



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
