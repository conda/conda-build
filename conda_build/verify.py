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


def verify(verify_type, ignore_scripts, **kargs):
    import_type = "verify.%s" % verify_type
    try:
        verify_module = __import__(import_type)
    except ImportError as e:
        print("can't find verify.recipe module, skipping verification")
        return False
    script_dir = join(verify_module.__path__[0], verify_type)
    verify_scripts = list_verify_script(script_dir)
    for verify_script in verify_scripts:
        if verify_script not in ignore_scripts:
            mod = getattr(__import__(import_type, fromlist=[verify_script]), verify_script)
            print("Running script %s.py" % verify_script)
            try:
                mod.verify(**kargs)
            except TypeError as e:
                raise VerifyError(e, verify_script)
    print("All scripts passed")


def verify_recipe(recipe):
    verify("recipe", context.ignore_recipe_verify_scripts, rendered_meta=recipe.meta,
           recipe_dir=recipe.path)


def verify_package(path_to_package):
    verify("package", context.ignore_package_verify_scripts, path_to_package=path_to_package)
