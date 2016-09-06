import unittest

from conda_build.conda_interface import MatchSpec

from conda_build.metadata import select_lines, handle_config_version


def test_select_lines():
    lines = """
test
test [abc] no
test [abc] # no

test [abc]
 'quoted # [abc] '
 "quoted # [abc] yes "
test # stuff [abc] yes
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }} # stuff [abc] yes
test {{ JINJA_VAR[:2] }} # stuff yes [abc]
test {{ JINJA_VAR[:2] }} # [abc] stuff yes
{{ environ["test"] }}  # [abc]
"""

    assert select_lines(lines, {'abc': True}) == """
test
test [abc] no
test [abc] # no

test
 'quoted'
 "quoted"
test
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
{{ environ["test"] }}
"""
    assert select_lines(lines, {'abc': False}) == """
test
test [abc] no
test [abc] # no

test {{ JINJA_VAR[:2] }}
"""


class HandleConfigVersionTests(unittest.TestCase):

    def test_python(self):
        for spec, ver, res_spec in [
                ('python', '3.4', 'python 3.4*'),
                ('python 2.7.8', '2.7', 'python 2.7.8'),
                ('python 2.7.8', '3.5', 'python 2.7.8'),
                ('python 2.7.8', None, 'python 2.7.8'),
                ('python', None, 'python'),
                ('python x.x', '2.7', 'python 2.7*'),
                ('python', '27', 'python 2.7*'),
                ('python', 27, 'python 2.7*'),
        ]:
            ms = MatchSpec(spec)
            self.assertEqual(handle_config_version(ms, ver),
                             MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          handle_config_version,
                          MatchSpec('python x.x'), None)

    def test_numpy(self):
        for spec, ver, res_spec, kwargs in [
                ('numpy', None, 'numpy', {}),
                ('numpy', 18, 'numpy 1.8*', {'dep_type': 'build'}),
                ('numpy', 18, 'numpy', {'dep_type': 'run'}),
                ('numpy', 110, 'numpy', {}),
                ('numpy x.x', 17, 'numpy 1.7*', {}),
                ('numpy x.x', 110, 'numpy 1.10*', {}),
                ('numpy 1.9.1', 18, 'numpy 1.9.1', {}),
                ('numpy 1.9.0 py27_2', None, 'numpy 1.9.0 py27_2', {}),
        ]:
            ms = MatchSpec(spec)
            self.assertEqual(handle_config_version(ms, ver, **kwargs),
                             MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          handle_config_version,
                          MatchSpec('numpy x.x'), None)
