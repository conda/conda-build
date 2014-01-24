# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import print_function, division, absolute_import

import sys
import os
import argparse

#from conda.cli import common
import conda.config as config
from conda_build import __version__


def main():
    p = argparse.ArgumentParser(
        description='tool for building conda packages'
    )

    p.add_argument(
        '-c', "--check",
        action = "store_true",
        help = "only check (validate) the recipe",
    )
    p.add_argument(
        "--no-binstar-upload",
        action = "store_false",
        help = "do not ask to upload the package to binstar",
        dest = 'binstar_upload',
        default = config.binstar_upload,
    )
    p.add_argument(
        "--output",
        action = "store_true",
        help = "output the conda package filename which would have been "
               "created and exit",
    )
    p.add_argument(
        '-s', "--source",
        action = "store_true",
        help = "only obtain the source (but don't build)",
    )
    p.add_argument(
        '-t', "--test",
        action = "store_true",
        help = "test package (assumes package is already build)",
    )
    p.add_argument(
        'recipe',
        action = "store",
        metavar = 'PATH',
        nargs = '+',
        help = "path to recipe directory",
    )
    p.add_argument(
        '--no-test',
        action='store_true',
        dest='notest',
        help="do not test the package"
    )
    p.add_argument(
        '-V', '--version',
        action = 'version',
        version = 'conda-build %s' % __version__,
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args.func(args, p)


def handle_binstar_upload(path, args):
    import subprocess
    from conda_build.external import find_executable

    if args.binstar_upload is None:
        args.yes = False
        args.dry_run = False
#        upload = common.confirm_yn(
#            args,
#            message="Do you want to upload this "
#            "package to binstar", default='yes', exit_no=False)
        upload = False
    else:
        upload = args.binstar_upload

    if not upload:
        print("""\
# If you want to upload this package to binstar.org later, type:
#
# $ binstar upload %s
""" % path)
        return

    binstar = find_executable('binstar')
    if binstar is None:
        sys.exit('''
Error: cannot locate binstar (required for upload)
# Try:
# $ conda install binstar
''')
    print("Uploading to binstar")
    args = [binstar, 'upload', path]
    if config.binstar_personal:
        args += ['--personal']
    subprocess.call(args)


def check_external():
    import os
    import conda_build.external as external

    if sys.platform.startswith('linux'):
        chrpath = external.find_executable('chrpath')
        if chrpath is None:
            sys.exit("""\
Error:
    Did not find 'chrpath' in: %s
    'chrpath' is necessary for building conda packages on Linux with
    relocatable ELF libraries.  You can install chrpath using apt-get,
    yum or conda.
""" % (os.pathsep.join(external.dir_paths)))


def execute(args, parser):
    import sys
    import shutil
    import tarfile
    import tempfile
    from os.path import abspath, isdir, isfile, join

    from conda.lock import Locked
    import conda_build.build as build
    import conda_build.source as source
    from conda_build.config import croot
    from conda_build.metadata import MetaData

    check_external()

    with Locked(croot):
        # get once all recipes
        main_recipes_dir = join(config.root_dir, 'conda-recipes')
        all_recipies = {}
        for root, dirs, files in os.walk(main_recipes_dir):
            for any_dir in dirs:
                any_dir_path = os.path.join(root, any_dir)
                if os.path.isfile(os.path.join(any_dir_path, "meta.yaml")):
                    if any_dir not in all_recipies:
                        all_recipies[any_dir] = [any_dir_path]
                    else:
                        all_recipies[any_dir].append(any_dir_path)
                        
        for arg in args.recipe:
            if isfile(arg):
                if arg.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
                    recipe_dir = tempfile.mkdtemp()
                    t = tarfile.open(arg, 'r:*')
                    t.extractall(path=recipe_dir)
                    t.close()
                    need_cleanup = True
                else:
                    print("Ignoring non-recipe: %s" % arg)
                    continue
            else:
                recipe_dir = abspath(arg)
                need_cleanup = False

            if not isdir(recipe_dir):
                # See if it's a spec and the directory is in conda-recipes
                if arg not in all_recipies:
                    sys.exit("Error: did not find any recipes for: "
                    "<%s>: Recipes Root Dir: "
                    "<%s> " % (arg, main_recipes_dir))
                elif len(all_recipies[arg]) > 1:
                    print('\nMultiple recipes with same name: <%s>' % arg)
                    for xrecipe in all_recipies[arg]:
                        print('    ', xrecipe)
                    sys.exit('Ambiguities: specify full recipe path')
                else:
                    recipe_dir = abspath(all_recipies[arg])

            m = MetaData(recipe_dir)
            binstar_upload = False
            if args.check and len(args.recipe) > 1:
                print(m.path)
            m.check_fields()
            if args.check:
                continue
            if args.output:
                print(build.bldpkg_path(m))
                continue
            elif args.test:
                build.test(m)
            elif args.source:
                source.provide(m.path, m.get_section('source'))
                print('Source tree in:', source.get_dir())
            else:
                build.build(m)
                if not args.notest:
                    build.test(m)
                binstar_upload = True

            if need_cleanup:
                shutil.rmtree(recipe_dir)

            if binstar_upload:
                handle_binstar_upload(build.bldpkg_path(m), args)


if __name__ == '__main__':
    main()
