import unittest
from os.path import join, dirname
from conda_build import verify


class TestVerify(unittest.TestCase):
    def test_list_verify_script(self):
        path_to_scripts = join(dirname(__file__), "test-verify-scripts/package")
        files = verify.list_verify_script(path_to_scripts)
        expected_scripts = [join(path_to_scripts, "test_package.py"),
                            join(path_to_scripts, "test_package_2.py")]
        self.assertListEqual(files, expected_scripts)

        path_to_scripts = join(dirname(__file__), "test-verify-scripts/recipe")
        files = verify.list_verify_script(path_to_scripts)
        self.assertListEqual(files, [join(path_to_scripts, "test_recipe.py")])

    def test_verify(self):
        path_to_scripts = join(dirname(__file__), "test-verify-scripts/package")
        verify.verify(path_to_scripts, "path_to_package_arg")

        path_to_scripts = join(dirname(__file__), "test-verify-scripts/recipe")
        verify.verify(path_to_scripts, "recipe_arg", "path_to_recipe_arg")

    def test_verify_no_script(self):
        path_to_script = "non/sense"
        verify.verify(path_to_script)
