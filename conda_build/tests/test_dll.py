import unittest
import operator
from os.path import join
#
from conda_build.dll import (
        LibraryDependencies,
        DynamicLibrary,
        LinuxDynamicLibrary,
        DarwinDynamicLibrary,
        Win32DynamicLibrary,
)


class TestLibraryDependencies(unittest.TestCase):
    def test_proper_construction(self):
        prefix = '/base/'
        not_prefix = '/definitelynottheprefix/'
        inside_set = set(['inside.so'])
        outside_set = set(['outside.so'])
        missing_set = set(['missing.so'])
        deps_list = [
                [(depname, join(prefix, depname)) for depname in inside_set],
                [(depname, join(not_prefix, depname)) for depname in outside_set],
                [(depname, None) for depname in missing_set],
        ]
        deps = reduce(operator.add, deps_list, [])
        ld = LibraryDependencies(deps, prefix)
        self.assertSetEqual(inside_set, ld.inside)
        self.assertSetEqual(outside_set, ld.outside)
        self.assertSetEqual(missing_set, ld.missing)


if __name__ == '__main__':
    unittest.main()
