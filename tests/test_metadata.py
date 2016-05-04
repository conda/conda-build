from contextlib import contextmanager
import unittest

from conda.resolve import MatchSpec

from conda_build.metadata import select_lines, handle_config_version, MetaData


def test_select_lines():
    lines = """
test
test [abc] no

test [abc]
test # [abc]
test # [abc] yes
test # stuff [abc] yes
"""

    assert select_lines(lines, {'abc': True}) == """
test
test [abc] no

test
test
test
test
"""
    assert select_lines(lines, {'abc': False}) == """
test
test [abc] no

"""

@contextmanager
def tmp_meta(spec, index=None):
    import os.path
    import shutil
    import tempfile
    import textwrap

    recipe_dir = tempfile.mkdtemp(prefix='tmp_recipe_')
    try:
        with open(os.path.join(recipe_dir, 'meta.yaml'), 'w') as fh:
            fh.write(textwrap.dedent(spec))
        m = MetaData(recipe_dir)
        if index is not None:
            m._index = index
        yield m
    finally:
        shutil.rmtree(recipe_dir)


class TestResolvedDepends(unittest.TestCase):
    def setUp(self):
        from dummy_index import DummyIndex
        index = DummyIndex()
        index.add_pkg('zlib', '1.2')
        index.add_pkg('python', '2.7.3', depends=('zlib',))
        index.add_pkg('python', '3.5.3')
        index.add_pkg('numpy', '1.9.2', 'py27', depends=('python 2.7.*',))
        index.add_pkg('numpy', '1.9.2', 'py35', depends=('python 3.5.*',))
        index.add_pkg('numpy', '1.10.1', 'py27', depends=('python 2.7.*',))
        index.add_pkg('numpy', '1.10.1', 'py35', depends=('python 3.5.*',))
        self.index = index

    def test_build_id(self):
        spec = """
        package:
            name: foo
            version: 2
        requirements:
            build:
                - python <3
                - numpy 1.* 
        """
        with tmp_meta(spec, index=self.index) as m:
            self.assertEqual(m.build_id(), 'py27_0')

    def test_resolve_build(self):
        spec = """
        package:
            name: foo
            version: 2
        requirements:
            build:
                - python <3
                - numpy 1.*
        """
        with tmp_meta(spec, index=self.index) as m:
            self.assertEqual(sorted(m.resolve_build_deps()),
                             ['numpy-1.10.1-py27_0.tar.bz2',
                              'python-2.7.3-0.tar.bz2',
                              'zlib-1.2-0.tar.bz2'])

    def test_pinned_specs(self):
        spec = """
        package:
            name: foo
            version: 2
        requirements:
            run:
                - python
                - numpy
            pin_from_build:
                - python x.*
                - numpy x.x.*
            build:
                - python >1,<3
                - numpy 1.9.*
        """
        with tmp_meta(spec, index=self.index) as m:
            self.assertEqual(sorted(m.pinned_specs()),
                             ['numpy 1.9.*',
                              'python 2.*'])
            self.assertEqual(m.build_id(), 'py2np19_0')

    def test_pinned_specs_python_default(self):
        spec = """
        package:
            name: foo
            version: 2
        requirements:
            run:
                - python
                - numpy
            pin_from_build:
                - numpy x.x.*
            build:
                - python >1,<3
                - numpy 1.9.*
        """
        with tmp_meta(spec, index=self.index) as m:
            # Despite the lack of a Python in the pin_from_build, we still
            # get a sensible pinned spec.
            self.assertEqual(sorted(m.pinned_specs()),
                             ['numpy 1.9.*',
                              'python 2.7.*'])

    def test_pin_non_build_dep(self):
        spec = """
        package:
            name: foo
            version: 2
        requirements:
            build:
                - numpy
            pin_from_build:
                - python x.*
                - numpy x.x.*
        """
        with self.assertRaises(ValueError):
            with tmp_meta(spec, index=self.index) as m:
                m.pinned_specs()


class HandleConfigVersionTests(unittest.TestCase):
    def test_python(self):
        for spec, ver, res_spec in [
            ('python',       '3.4', 'python 3.4*'),
            ('python 2.7.8', '2.7', 'python 2.7.8'),
            ('python 2.7.8', '3.5', 'python 2.7.8'),
            ('python 2.7.8', None,  'python 2.7.8'),
            ('python',       None,  'python'),
            ('python x.x',   '2.7', 'python 2.7*'),
            ('python',       '27',  'python 2.7*'),
            ('python',        27,   'python 2.7*'),
            ]:
            ms = MatchSpec(spec)
            self.assertEqual(handle_config_version(ms, ver),
                             MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          handle_config_version,
                          MatchSpec('python x.x'), None)

    def test_numpy(self):
        for spec, ver, res_spec in [
            ('numpy',        None,  'numpy'),
            ('numpy',        18,    'numpy'),
            ('numpy',        110,   'numpy'),
            ('numpy x.x',    17,    'numpy 1.7*'),
            ('numpy x.x',    110,   'numpy 1.10*'),
            ('numpy 1.9.1',  18,    'numpy 1.9.1'),
            ('numpy 1.9.0 py27_2', None,  'numpy 1.9.0 py27_2'),
            ]:
            ms = MatchSpec(spec)
            self.assertEqual(handle_config_version(ms, ver),
                             MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          handle_config_version,
                          MatchSpec('numpy x.x'), None)
