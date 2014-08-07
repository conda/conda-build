import os
import unittest
import operator
from os.path import join
#
from conda_build.link import (
        ExternalLinkage,
        RecipeCorrectButBuildScriptBroken,
        BrokenLinkage,
)

from conda_build.dll import (
        find_executable,
        ProcessWrapper,
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

def get_something_in_prefix(prefix):
    from conda_build.build import create_env
    create_env(prefix, ['python'], verbose=True)
    # FIXME: how to make this OS agnostic?
    _find = ProcessWrapper(find_executable('find'))
    found_python = _find(prefix, '-name', 'python')
    assert found_python
    return found_python

class TestDynamicLibrary(unittest.TestCase):

    def build_dynamic_library(self):
        from conda_build.build import BuildRoot
        build_root = BuildRoot()
        something_in_prefix = get_something_in_prefix(build_root.prefix)
        # FIXME: test more than Linux
        dynamic_library = LinuxDynamicLibrary(something_in_prefix, build_root)
        # clear it out
        dynamic_library.link_errors = []
        dynamic_library.inside = set()
        dynamic_library.outside = set()
        dynamic_library.missing = set()
        return dynamic_library

    def test_construction(self):
        assert self.build_dynamic_library()

    def test_process_outside_targets(self):
        # FIXME: test allowed_outside
        outside_set = set(['external_linkage.so'])

        def test_external_linkage():
            dl = self.build_dynamic_library()
            # now munge dynamic_library.{inside,outside,missing} for our purposes
            dl.outside = outside_set.copy()
            dl._process_outside_targets()
            is_correct_type = lambda obj: isinstance(obj, ExternalLinkage)
            assert all(map(is_correct_type, dl.link_errors))
            assert len(dl.link_errors) == len(outside_set)

        def test_recipe_correct_but_build_script_broken():
            dl = self.build_dynamic_library()
            # now munge dynamic_library.{inside,outside,missing} for our purposes
            dl.outside = outside_set.copy()
            dl.build_root = dict.fromkeys(dl.outside)
            dl._process_outside_targets()
            is_correct_type = lambda obj: \
                    isinstance(obj, RecipeCorrectButBuildScriptBroken)
            assert all(map(is_correct_type, dl.link_errors))
            assert len(dl.link_errors) == len(outside_set)

        test_external_linkage()
        test_recipe_correct_but_build_script_broken()

    def test_process_missing_targets(self):
        dl = self.build_dynamic_library()
        # now munge dynamic_library.{inside,outside,missing} for our purposes
        num_missing = 5
        dl.missing = map(str, range(num_missing))
        dl._process_missing_targets()
        self.assertEqual(len(dl.link_errors), num_missing)

    def test_arbitrate_realtive(self):
        arbitrate_relative = DynamicLibrary.arbitrate_relative
        prefix = '/some/absolute'
        relative_path = 'dep.so'
        absolute_path = join(prefix, relative_path)
        correct = [absolute_path, relative_path]
        # test absolute
        output = arbitrate_relative(absolute_path, prefix)
        self.assertListEqual(correct, list(output))
        # test relative
        output = arbitrate_relative(relative_path, prefix)
        self.assertListEqual(correct, list(output))
        # demonstrate failure of trailing slash in prefix
        output = arbitrate_relative(relative_path, prefix + '/')
        self.assertNotEqual(correct, list(output))


if __name__ == '__main__':
    unittest.main()
