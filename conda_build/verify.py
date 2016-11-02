from os.path import join
import pkgutil
from .config import context
from .exceptions import VerifyError


def list_verify_script(path_to_script):
    verify_modules = pkgutil.iter_modules([path_to_script])
    files = []
    for _, name, _ in verify_modules:
        files.append(name)
    return files


def verify_package(path_to_package):
    pass
    # try:
    #     verify_module = __import__("verify.package")
    # except ImportError as e:
    #     print("can't find verify.package module, skipping verification")
    #     return False
    # package_dir = join(verify_module.__path__[0], "package")
    # verify(package_dir, context.ignore_package_verify_scripts, path_to_package)


def verify_recipe(recipe):
    try:
        verify_module = __import__("verify.recipe")
    except ImportError as e:
        print("can't find verify.recipe module, skipping verification")
        return False
    recipe_dir = join(verify_module.__path__[0], "recipe")

    verify_scripts = list_verify_script(recipe_dir)
    for verify_script in verify_scripts:
        if verify_script not in context.ignore_recipe_verify_scripts:
            mod = getattr(__import__("verify.recipe", fromlist=[verify_script]), verify_script)
            print("Running script %s.py" % verify_script)
            try:
                mod.verify(recipe.meta, recipe.path)
            except TypeError as e:
                raise VerifyError(e, verify_script)
    print("All scripts passed")
