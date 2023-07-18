# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import shutil
import sys
from os.path import abspath, exists, expanduser, isdir, join

from conda_build.os_utils.external import find_executable
from conda_build.post import mk_relative_osx
from conda_build.utils import check_call_env, get_site_packages, rec_glob


def relink_sharedobjects(pkg_path, build_prefix):
    """
    invokes functions in post module to relink to libraries in conda env

    :param pkg_path: look for shared objects to relink in pkg_path
    :param build_prefix: path to conda environment which contains lib/. to find
        runtime libraries.

    .. note:: develop mode builds the extensions in place and makes a link to
        package in site-packages/. The build_prefix points to conda environment
        since runtime libraries should be loaded from environment's lib/. first
    """
    # find binaries in package dir and make them relocatable
    bin_files = rec_glob(pkg_path, [".so"])
    for b_file in bin_files:
        if sys.platform == "darwin":
            mk_relative_osx(b_file, build_prefix)
        else:
            print("Nothing to do on Linux or Windows.")


def write_to_conda_pth(sp_dir, pkg_path):
    """
    Append pkg_path to conda.pth in site-packages directory for current
    environment. Only add path if it doens't already exist.

    :param sp_dir: path to site-packages/. directory
    :param pkg_path: the package path to append to site-packes/. dir.
    """
    c_file = join(sp_dir, "conda.pth")
    with open(c_file, "a") as f:
        with open(c_file) as cf:
            # make sure file exists, before we try to read from it hence nested
            # in append with block
            # expect conda.pth to be small so read it all in at once
            pkgs_in_dev_mode = cf.readlines()

        # only append pkg_path if it doesn't already exist in conda.pth
        if pkg_path + "\n" in pkgs_in_dev_mode:
            print("path exists, skipping " + pkg_path)
        else:
            f.write(pkg_path + "\n")
            print("added " + pkg_path)


def get_setup_py(path_):
    """Return full path to setup.py or exit if not found"""
    # build path points to source dir, builds are placed in the
    setup_py = join(path_, "setup.py")

    if not exists(setup_py):
        sys.exit(f"No setup.py found in {path_}. Exiting.")

    return setup_py


def _clean(setup_py):
    """
    This invokes:
    $ python setup.py clean

    :param setup_py: path to setup.py
    """
    # first call setup.py clean
    cmd = ["python", setup_py, "clean"]
    check_call_env(cmd)
    print("Completed: " + " ".join(cmd))
    print("===============================================")


def _build_ext(setup_py):
    """
    Define a develop function - similar to build function
    todo: need to test on win32 and linux

    It invokes:
    $ python setup.py build_ext --inplace

    :param setup_py: path to setup.py
    """

    # next call setup.py develop
    cmd = ["python", setup_py, "build_ext", "--inplace"]
    check_call_env(cmd)
    print("Completed: " + " ".join(cmd))
    print("===============================================")


def _uninstall(sp_dir, pkg_path):
    """
    Look for pkg_path in conda.pth file in site-packages directory and remove
    it. If pkg_path is not found in conda.pth, it means package is not
    installed in 'development mode' via conda develop.

    :param sp_dir: path to site-packages/. directory
    :param pkg_path: the package path to be uninstalled.
    """
    o_c_pth = join(sp_dir, "conda.pth")
    n_c_pth = join(sp_dir, "conda.pth.temp")
    found = False
    with open(n_c_pth, "w") as new_c:
        with open(o_c_pth) as orig_c:
            for line in orig_c:
                if line != pkg_path + "\n":
                    new_c.write(line)
                else:
                    print("uninstalled: " + pkg_path)
                    found = True

    if not found:
        print("conda.pth does not contain path: " + pkg_path)
        print("package not installed via conda develop")

    shutil.move(n_c_pth, o_c_pth)


def execute(
    recipe_dirs,
    prefix=sys.prefix,
    no_pth_file=False,
    build_ext=False,
    clean=False,
    uninstall=False,
):
    if not isdir(prefix):
        sys.exit(
            """\
Error: environment does not exist: %s
#
# Use 'conda create' to create the environment first.
#"""
            % prefix
        )

    assert find_executable("python", prefix=prefix)

    # current environment's site-packages directory
    sp_dir = get_site_packages(
        prefix, ".".join((str(sys.version_info.major), str(sys.version_info.minor)))
    )

    if isinstance(recipe_dirs, str):
        recipe_dirs = [recipe_dirs]

    for path in recipe_dirs:
        pkg_path = abspath(expanduser(path))

        if uninstall:
            # uninstall then exit - does not do any other operations
            _uninstall(sp_dir, pkg_path)
            return

        if clean or build_ext:
            setup_py = get_setup_py(pkg_path)
            if clean:
                _clean(setup_py)
                if not build_ext:
                    return

            # build extensions before adding to conda.pth
            if build_ext:
                _build_ext(setup_py)

        if not no_pth_file:
            write_to_conda_pth(sp_dir, pkg_path)

        # go through the source looking for compiled extensions and make sure
        # they use the conda environment for loading libraries at runtime
        relink_sharedobjects(pkg_path, prefix)
        print("completed operation for: " + pkg_path)
