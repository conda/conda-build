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
        for d, f, r in [
            ('lib', 'bin/python', '../lib'),
            ('lib', 'lib/libhdf5.so', '.'),
            ('lib', 'lib/python2.6/foobar.so', '..'),
            ('lib', 'lib/python2.6/lib-dynload/zlib.so', '../..'),
            ('lib', 'lib/python2.6/site-packages/pyodbc.so', '../..'),
            ('lib', 'lib/python2.6/site-packages/bsdiff3/core.so', '../../..'),
            ('lib', 'xyz', './lib'),
            ('lib', 'bin/somedir/cmd', '../../lib'),
            ('lib', 'bin/somedir/somedir2/cmd', '../../../lib'),
            ]:
            self.assertEqual(utils.relative(f, d), r)

    def test_relative_prefix(self):
        for d, f, r in [
            ('.', 'xyz', '.'),
            ('.', 'bin/xyz', '..'),
            ('.', 'a/b/xyz', '../..'),
            ('.', 'a/b/c/xyz', '../../..'),
            ('.', 'a/b/c/d/xyz', '../../../..'),
            ]:
            self.assertEqual(utils.relative(f, d), r)

    def test_relative_subdirs(self):
        for d, f, r in [
            ('lib/sub', 'bin/somedir/cmd', '../../lib/sub'),
            ('lib/sub', 'bin/python', '../lib/sub'),
            ('lib/sub', 'lib/sub/libhdf5.so', '.'),
            ('a/b/c', 'a/b/c/libhdf5.so', '.'),
            ('a/b/c/d', 'a/b/x/y/libhdf5.so', '../../c/d'),
            ('a/b/c/d', 'a/b/c/y/libhdf5.so', '../d'),
            ]:
            self.assertEqual(utils.relative(f, d), r)
