import os
from .exceptions import VerifyError
import sys


def can_import_importlib():
    return sys.version_info.major >= 3 and sys.version_info.minor >= 3


if can_import_importlib():
    from importlib.machinery import SourceFileLoader
else:
    # imp.load_source has been deprecated in python3.3. So importlib should be used for versions
    #   for versions of python greater than 3.3
    import imp


def list_verify_script(path_to_script):
    import pkgutil
    verify_modules = pkgutil.iter_modules([path_to_script])
    files = []
    for loader, name, _ in verify_modules:
        files.append(os.path.join(loader.path, name))
    return files


def verify(verify_path, *args):
    verify_scripts = list_verify_script(verify_path)

    for verify_script in verify_scripts:
        script = "%s.py"%verify_script
        print("Running script %s" % script)
        if can_import_importlib():
            mod = SourceFileLoader("test", verify_script).load_module()
        else:
            mod = imp.load_source("test", script)
        try:
            mod.verify(*args)
        except AttributeError as e:
            raise VerifyError(e, script)
    print("All scripts passed")


def verify_package(path_to_package, config):
    verify_path = os.path.join(config.verify_scripts_path, "package")
    verify(verify_path, path_to_package)


def verify_recipe(recipe, config):
    verify_path = os.path.join(config.verify_scripts_path, "recipe")
    verify(verify_path, recipe.meta, recipe.path)
