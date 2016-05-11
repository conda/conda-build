import unittest

import conda_build._link as _link


class TestLink(unittest.TestCase):

    def test_pyc_f_2(self):
        self.assertEqual(_link.pyc_f('sp/utils.py', (2, 7, 9)),
                                     'sp/utils.pyc')

    def test_pyc_f_3(self):
        for f, r in [
                ('sp/utils.py',
                 'sp/__pycache__/utils.cpython-34.pyc'),
                ('sp/foo/utils.py',
                 'sp/foo/__pycache__/utils.cpython-34.pyc'),
        ]:
            self.assertEqual(_link.pyc_f(f, (3, 4, 2)), r)
