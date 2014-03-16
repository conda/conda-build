# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import print_function, division, absolute_import

import sys
import os.path
import argparse
import subprocess
import yaml

#from conda.cli import common
import conda.config as config
from conda_build import __version__
from conda.install import rm_rf

if sys.version_info < (3,):
    from xmlrpclib import ServerProxy
else:
    from xmlrpc.client import ServerProxy


def main():
    p = argparse.ArgumentParser(
        description='tool for building conda packages just using pip install'
    )

    p.add_argument(
        "--no-binstar-upload",
        action = "store_false",
        help = "do not ask to upload the package to binstar",
        dest = 'binstar_upload',
        default = config.binstar_upload,
    )
    p.add_argument(
        'pypi_name',
        action="store",
        metavar='<PYPI_NAME>',
        nargs=1,
        help="name of package on PYPI"
    )
    p.add_argument(
        "--release",
        action='store',
        nargs = 1,
        help = "specify version of package to build",
        default="latest"
    )
    p.add_argument(
        "--pypi-url",
        action = "store",
        nargs=1,
        default='http://pypi.python.org/pypi',
        help = "Url to use for PyPI",
        ) 
    p.add_argument(
        '-V', '--version',
        action = 'version',
        version = 'conda-pipbuild %s' % __version__,
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
    subprocess.call(args)

# Run conda skeleton pypi {0} --no-download --no-prompt
# Check to be sure all the dependencies are already in conda repositories
#  if not, recursively build them...
# Modify the recipe directory to make a new recipe with just the dependencies
#   and a build script that says pip install for both build.sh and build.bat

def conda_package_exists(pkgname, version=None):
    from conda.api import get_index
    from conda.resolve import MatchSpec, Resolve

    pyver = 'py%s' % sys.version[:3].replace('.','')
    index = get_index(use_cache = True)
    r = Resolve(index)
    try:
        pkgs = r.get_pkgs(MatchSpec(pkgname))
    except RuntimeError:
        return False
    exists = False
    for pkg in pkgs:
        match_pyver = pkg.build.startswith(pyver)
        if not match_pyver:
            continue
        if version and pkg.version != version:
            continue
        exists = True
        break
    return exists

skeleton_template = "conda skeleton pypi {0} --no-prompt"
skeleton_template_wversion = "conda skeleton pypi {0} --version {1} --no-prompt"
build_template = "conda build {0} --no-binstar-upload --no-test"

meta_template = """package:
  name: {packagename}
  version: !!str {version}

requirements:
  build:
    - python
    - pip{depends}

  run:
    - python{depends}

about:
  home: {homeurl}
  license: {license}
  summary: {summary}
"""

def build_recipe(package):
    if os.path.isdir(package.lower()):
        rm_rf(package.lower())
    args = skeleton_template.format(package).split()
    print("Creating standard recipe for {0}".format(package.lower()))
    result = subprocess.check_output(args, stderr=subprocess.STDOUT)
    output = result.strip().split('\n')
    if output[-1] == 'Done':
        direc = output[-2].split()[-1]
    else:
        raise RuntimeError("Incorrect output from build_recipe: %s" % output)
    return os.path.abspath(direc)

def convert_recipe(direc, package):
    print("Converting recipe in {0}".format(direc))
    build = 'pip install %s\n' % package
    # convert build.sh file and bld.bat file
    filenames = ['build.sh', 'bld.bat']
    for name in filenames:
        with open(os.path.join(direc, name),'w') as fid:
            fid.write(build)
    # convert meta.yaml file
    with open(os.path.join(direc,'meta.yaml')) as fid:
        mystr = fid.read()
        fid.seek(0)
        meta = yaml.load(fid)

    bdep = meta['requirements']['build']
    bdep.remove('python')
    try:
        bdep.remove('setuptools')
        bdep.remove('pip')
    except ValueError:
        pass
    depends = bdep
    indent = '\n    - '
    d = {}
    d['packagename'] = meta['package']['name']
    d['version'] = meta['package']['version']
    if depends:
        d['depends'] = indent.join([''] + depends)
    else:
        d['depends'] = ''
    d['homeurl'] = meta['about']['home']
    d['license'] = meta['about']['license']
    d['summary'] = meta['about']['summary']

    with open(os.path.join(direc,'meta.yaml'),'w') as fid:
        fid.write(meta_template.format(**d))

    return depends

def build_package(package):
    directory = build_recipe(package)
    dependencies = convert_recipe(directory, package)
    for depend in dependencies:
        if not conda_package_exists(depend):
            temp = build_package(depend)
    args = build_template.format(directory).split()
    print("Building conda package for {0}".format(package.lower()))
    result = subprocess.Popen(args).wait()
    #rm_rf(directory)
    return result

def execute(args, parser):

    client = ServerProxy(args.pypi_url)
    package = args.pypi_name[0]
    all_versions = True
    if args.release == 'latest':
        all_versions = False

    releases = client.package_releases(package, all_versions)
    if not releases:
        sys.exit("Error:  PyPI does not have a package named %s" % arg)


    build_package(package)

    if args.binstar_upload:
        handle_binstar_upload(build.bldpkg_path(m), args)


if __name__ == '__main__':
    main()
