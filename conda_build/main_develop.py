# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
from os.path import join, isdir, abspath, expanduser, exists
import shutil

from conda.cli.common import add_parser_prefix, get_prefix
from conda.cli.conda_argparse import ArgumentParser
from conda_build.main_build import args_func
from conda_build.post import mk_relative_osx
from conda_build.utils import _check_call, rec_glob

from conda.install import linked


def main():
    p = ArgumentParser(
        description="""

Install a Python package in 'development mode'.

This works by creating a conda.pth file in site-packages."""
        # TODO: Use setup.py to determine any entry-points to install.
    )

    p.add_argument(
        'source',
        action="store",
        metavar='PATH',
        nargs='+',
        help="Path to the source directory."
    )
    p.add_argument('-npf', '--no-pth-file',
                   action='store_true',
                   help=("Relink compiled extension dependencies against "
                         "libraries found in current conda env. "
                         "Do not add source to conda.pth."))
    p.add_argument('-b', '--build_ext',
                   action='store_true',
                   help=("Build extensions inplace, invoking: "
                         "python setup.py build_ext --inplace; "
                         "add to conda.pth; relink runtime libraries to "
                         "environment's lib/."))
    p.add_argument('-c', '--clean',
                   action='store_true',
                   help=("Invoke clean on setup.py: "
                         "python setup.py clean "
                         "use with build_ext to clean before building."))
    p.add_argument('-u', '--uninstall',
                   action='store_true',
                   help=("Removes package if installed in 'development mode' "
                         "by deleting path from conda.pth file. Ignore other "
                         "options - just uninstall and exit"))

    add_parser_prefix(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def relink_sharedobjects(pkg_path, build_prefix):
    '''
    invokes functions in post module to relink to libraries in conda env

    :param pkg_path: look for shared objects to relink in pkg_path
    :param build_prefix: path to conda environment which contains lib/. to find
        runtime libraries.

    .. note:: develop mode builds the extensions in place and makes a link to
        package in site-packages/. The build_prefix points to conda environment
        since runtime libraries should be loaded from environment's lib/. first
    '''
    # find binaries in package dir and make them relocatable
    bin_files = rec_glob(pkg_path, ['.so'])
    for b_file in bin_files:
        if sys.platform == 'darwin':
            mk_relative_osx(b_file, build_prefix)
        else:
            print("Nothing to do on Linux or Windows.")


def write_to_conda_pth(sp_dir, pkg_path):
    '''
    Append pkg_path to conda.pth in site-packages directory for current
    environment. Only add path if it doens't already exist.

    :param sp_dir: path to site-packages/. directory
    :param pkg_path: the package path to append to site-packes/. dir.
    '''
    c_file = join(sp_dir, 'conda.pth')
    with open(c_file, 'a') as f:
        with open(c_file, 'r') as cf:
            # make sure file exists, before we try to read from it hence nested
            # in append with block
            # expect conda.pth to be small so read it all in at once
            pkgs_in_dev_mode = cf.readlines()

        # only append pkg_path if it doesn't already exist in conda.pth
        if pkg_path + '\n' in pkgs_in_dev_mode:
            print("path exits, skipping " + pkg_path)
        else:
            f.write(pkg_path + '\n')
            print("added " + pkg_path)


def get_site_pkg(prefix, py_ver):
    '''
    Given the path to conda environment, find the site-packages directory

    :param prefix: path to conda environment. Look here for current
        environment's site-packages
    :returns: absolute path to site-packages directory
    '''
    # get site-packages directory
    stdlib_dir = join(prefix, 'Lib' if sys.platform == 'win32' else
                      'lib/python%s' % py_ver)
    sp_dir = join(stdlib_dir, 'site-packages')

    return sp_dir


def get_setup_py(path_):
    ''' Return full path to setup.py or exit if not found '''
    # build path points to source dir, builds are placed in the
    setup_py = join(path_, 'setup.py')

    if not exists(setup_py):
        sys.exit("No setup.py found in {0}. Exiting.".format(path_))

    return setup_py


def clean(setup_py):
    '''
    This invokes:
    $ python setup.py clean

    :param setup_py: path to setup.py
    '''
    # first call setup.py clean
    cmd = ['python', setup_py, 'clean']
    _check_call(cmd)
    print("Completed: " + " ".join(cmd))
    print("===============================================")


def build_ext(setup_py):
    '''
    Define a develop function - similar to build function
    todo: need to test on win32 and linux

    It invokes:
    $ python setup.py build_ext --inplace

    :param setup_py: path to setup.py
    '''

    # next call setup.py develop
    cmd = ['python', setup_py, 'build_ext', '--inplace']
    _check_call(cmd)
    print("Completed: " + " ".join(cmd))
    print("===============================================")


def uninstall(sp_dir, pkg_path):
    '''
    Look for pkg_path in conda.pth file in site-packages directory and remove
    it. If pkg_path is not found in conda.pth, it means package is not
    installed in 'development mode' via conda develop.

    :param sp_dir: path to site-packages/. directory
    :param pkg_path: the package path to be uninstalled.
    '''
    o_c_pth = join(sp_dir, 'conda.pth')
    n_c_pth = join(sp_dir, 'conda.pth.temp')
    found = False
    with open(n_c_pth, 'w') as new_c:
        with open(o_c_pth, 'r') as orig_c:
            for line in orig_c:
                if line != pkg_path + '\n':
                    new_c.write(line)
                else:
                    print("uninstalled: " + pkg_path)
                    found = True

    if not found:
        print("conda.pth does not contain path: " + pkg_path)
        print("package not installed via conda develop")

    shutil.move(n_c_pth, o_c_pth)


def execute(args, parser):
    prefix = get_prefix(args)
    if not isdir(prefix):
        sys.exit("""\
Error: environment does not exist: %s
#
# Use 'conda create' to create the environment first.
#""" % prefix)
    for package in linked(prefix):
        name, ver, _ = package .rsplit('-', 2)
        if name == 'python':
            py_ver = ver[:3]  # x.y
            break
    else:
        raise RuntimeError("python is not installed in %s" % prefix)

    # current environment's site-packages directory
    sp_dir = get_site_pkg(prefix, py_ver)

    for path in args.source:
        pkg_path = abspath(expanduser(path))

        if args.uninstall:
            # uninstall then exit - does not do any other operations
            uninstall(sp_dir, pkg_path)
            sys.exit(0)

        if args.clean or args.build_ext:
            setup_py = get_setup_py(pkg_path)
            if args.clean:
                clean(setup_py)
                if not args.build_ext:
                    sys.exit(0)

            # build extensions before adding to conda.pth
            if args.build_ext:
                build_ext(setup_py)

        if not args.no_pth_file:
            write_to_conda_pth(sp_dir, pkg_path)

        # go through the source looking for compiled extensions and make sure
        # they use the conda environment for loading libraries at runtime
        relink_sharedobjects(pkg_path, prefix)
        print("completed operation for: " + pkg_path)

if __name__ == '__main__':
    main()
