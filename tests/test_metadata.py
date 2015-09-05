import unittest

from conda.resolve import MatchSpec

from conda_build.metadata import select_lines, special_spec


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

class SpecialSpecTests(unittest.TestCase):

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
            self.assertEqual(special_spec(ms, ver), MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          special_spec, MatchSpec('python x.x'), None)

    def test_numpy(self):
        for spec, ver, res_spec in [
            ('numpy',        None,  'numpy'),
            ('numpy',        18,    'numpy'),
            ('numpy x.x',    17,    'numpy 1.7*'),
            ('numpy 1.9.1',  18,    'numpy 1.9.1'),
            ('numpy 1.9.0 py27_2', None,  'numpy 1.9.0 py27_2'),
            ]:
            ms = MatchSpec(spec)
            self.assertEqual(special_spec(ms, ver), MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          special_spec, MatchSpec('numpy x.x'), None)
