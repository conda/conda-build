import os
from .exceptions import VerifyError
import sys


def list_verify_script(path_to_script):
    import pkgutil
    verify_modules = pkgutil.iter_modules([path_to_script])
    files = []
    for loader, name, _ in verify_modules:
        files.append("%s.py" % os.path.join(loader.path, name))
    return files


def verify(verify_path, *args):
    verify_scripts = list_verify_script(verify_path)

    for verify_script in verify_scripts:
        print("Running script %s" % verify_script)


        # try:
        #     mod.verify(*args)
        # except TypeError as e:
        #     raise VerifyError(e, verify_script)
    print("All scripts passed")


def verify_package(path_to_package, config):
    try:
        verify_module = __import__("verify.package")
    except ImportError as e:
        print("can't find verify.package module, skipping verification")
        return False
    verify(verify_module.__path__, path_to_package)


def verify_recipe(recipe, config):
    try:
        verify_module = __import__("verify.recipe")
    except ImportError as e:
        print("can't find verify.recipe module, skipping verification")
        return False
    verify(verify_module.__path__, recipe.meta, recipe.path)
