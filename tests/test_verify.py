import unittest
from os.path import join, dirname
from conda_build import verify
from conda_build.exceptions import VerifyError


class TestVerify(unittest.TestCase):
    def test_list_verify_script(self):
        path_to_scripts = join(dirname(__file__), "test-verify-scripts/package")
        files = verify.list_verify_script(path_to_scripts)
        expected_scripts = ["test_package", "test_package_2"]
        self.assertListEqual(files, expected_scripts)

        path_to_scripts = join(dirname(__file__), "test-verify-scripts/recipe")
        files = verify.list_verify_script(path_to_scripts)
        expected_scripts = ["test_recipe"]
        self.assertListEqual(files, expected_scripts)

    def test_no_verify_module(self):
        self.assertFalse(verify.verify("nonsense", []))
