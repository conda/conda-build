# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import print_function, division, absolute_import

import sys
import os.path
import subprocess
import yaml

#from conda.cli import common
import conda.config as cc
from conda.cli.conda_argparse import ArgumentParser

from conda_build.main_build import args_func
from conda.install import rm_rf
import conda_build.build as build
from conda_build.metadata import MetaData
from conda_build import utils

if sys.version_info < (3,):
    from xmlrpclib import ServerProxy
else:
    from xmlrpc.client import ServerProxy


def main():
    p = ArgumentParser(
        description="""
Tool for building conda packages using pip install. NOTE: this command is
experimental.  The recommended way to build conda packages from packages on
PyPI is using conda skeleton pypi and conda build.
        """,
    )

    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest='binstar_upload',
        default=cc.binstar_upload,
    )
    p.add_argument(
        "--anaconda-upload",
        action="store_true",
        help="Upload the package to anaconda.org.",
        dest='binstar_upload',
        default=cc.binstar_upload,
    )
    p.add_argument(
        'pypi_name',
        action="store",
        metavar='<PYPI_NAME>',
        nargs=1,
        help="Name of package on PyPI."
    )
    p.add_argument(
        "--release",
        action='store',
        nargs=1,
        help="Version of the package to build.",
        default="latest"
    )
    p.add_argument(
        "--pypi-url",
        action="store",
        default='http://pypi.python.org/pypi',
        help="Url to use for PyPI.",
    )
    p.add_argument(
        "--noarch-python",
        action="store_true",
        default=False,
        help="Creates package as noarch")
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def handle_binstar_upload(path):
    from conda_build.external import find_executable
    binstar = find_executable('anaconda')
    if binstar is None:
        sys.exit('''
Error: cannot locate anaconda command (required for upload)
# Try:
# $ conda install anaconda-client
''')
    print("Uploading to anaconda.org")
    args = [binstar, 'upload', path]
    subprocess.call(args)

# Run conda skeleton pypi {0} --no-download --no-prompt
# Check to be sure all the dependencies are already in conda repositories
#  if not, recursively build them...
# Modify the recipe directory to make a new recipe with just the dependencies
#   and a build script that says pip install for both build.sh and build.bat

skeleton_template = "conda skeleton pypi {0} --no-prompt"
skeleton_template_wversion = "conda skeleton pypi {0} --version {1} --no-prompt"
build_template = "conda build {0} --no-anaconda-upload --no-test"

meta_template = """package:
  name: {packagename}
  version: !!str {version}

{build_comment}build:
  {noarch_python_comment}noarch_python: True

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


def build_recipe(package, version=None):
    if version:
        dirname = package.lower() + "-" + version
    else:
        dirname = package.lower()
    if os.path.isdir(dirname):
        rm_rf(dirname)
    if version is None:
        args = skeleton_template.format(package).split()
    else:
        args = skeleton_template_wversion.format(package, version).split()
    print("Creating standard recipe for {0}".format(dirname))
    try:
        result = utils.execute(args, check_exit_code=True)
    except subprocess.CalledProcessError as err:
        print(err.output)
        raise RuntimeError((" ".join(args)))

    output = result.strip().splitlines()
    if output[-1] == 'Done':
        direc = output[-2].split()[-1]
    else:
        raise RuntimeError("Incorrect output from build_recipe: %s" % output)
    return os.path.abspath(direc)


def convert_recipe(direc, package, noarch_python=False):
    print("Converting recipe in {0}".format(direc))
    buildstr = 'pip install %s\n' % package
    # convert build.sh file and bld.bat file
    filenames = ['build.sh', 'bld.bat']
    for name in filenames:
        with open(os.path.join(direc, name), 'w') as fid:
            fid.write(buildstr)
    # convert meta.yaml file
    with open(os.path.join(direc, 'meta.yaml')) as fid:
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

    if noarch_python:
        d['build_comment'] = ''
        d['noarch_python_comment'] = ''
    else:
        d['build_comment'] = '# '
        d['noarch_python_comment'] = '# '

    with open(os.path.join(direc, 'meta.yaml'), 'w') as fid:
        fid.write(meta_template.format(**d))

    return depends


def get_all_dependencies(package, version):
    import conda.config
    prefix = os.path.join(conda.config.default_prefix, 'envs', '_pipbuild_')
    cmd1 = "conda create -n _pipbuild_ --yes python pip"
    print(cmd1)
    utils.execute(cmd1.split())
    cmd2 = "%s/bin/pip install %s==%s" % (prefix, package, version)
    print(cmd2)
    try:
        execute(cmd2.split(), check_exit_code=True)
    except subprocess.CalledProcessError:
        raise RuntimeError("Could not pip install %s==%s" % (package, version))

    cmd3args = ['%s/bin/python' % prefix, '__tmpfile__.py']
    fid = open('__tmpfile__.py', 'w')
    fid.write("import pkg_resources;\n")
    fid.write("reqs = pkg_resources.get_distribution('%s').requires();\n" %
              package)
    fid.write("print([(req.key, req.specs) for req in reqs])\n")
    fid.close()
    print("Getting dependencies...")
    output, _ = utils.execute(cmd3args, check_exit_code=True)
    deps = eval(output)
    os.unlink('__tmpfile__.py')
    depends = []
    for dep in deps:
        if len(dep[1]) == 2 and dep[1][0] == '==':
            depends.append(dep[0] + ' ' + dep[1][1])
        else:
            depends.append(dep[0])
    cmd4 = "conda remove -n _pipbuild_ --yes --all"
    utils.execute(cmd4.split())
    return depends


def make_recipe(package, version, noarch_python=False):
    if version is None:
        release = client.package_releases(package)
        if len(release) > 0:
            version = release[0]
        else:
            raise RuntimeError("Empty releases for %s" % package)
    depends = get_all_dependencies(package, version)
    dirname = package.lower() + "-" + version
    if os.path.isdir(dirname):
        rm_rf(dirname)
    os.mkdir(dirname)
    direc = os.path.abspath(dirname)
    build = 'pip install %s==%s\n' % (package, version)
    # write build.sh file and bld.bat file
    filenames = ['build.sh', 'bld.bat']
    for name in filenames:
        with open(os.path.join(direc, name), 'w') as fid:
            fid.write(build)

    indent = '\n    - '
    d = {}
    d['packagename'] = package
    d['version'] = version
    if depends:
        d['depends'] = indent.join([''] + depends)
    else:
        d['depends'] = ''

    data = client.release_data(package, version)
    if not data:
        raise RuntimeError("Cannot get data for %s-%s" % (package, version))

    license_classifier = "License :: OSI Approved ::"
    if 'classifiers' in data:
        licenses = [classifier.lstrip(license_classifier) for classifier in
                    data['classifiers'] if classifier.startswith(license_classifier)]
    else:
        licenses = []

    if not licenses:
        license = data.get('license', 'UNKNOWN') or 'UNKNOWN'
    else:
        license = ' or '.join(licenses)

    d['homeurl'] = data['home_page']
    d['license'] = license
    d['summary'] = repr(data['summary'])

    if noarch_python:
        d['build_comment'] = ''
        d['noarch_python_comment'] = ''
    else:
        d['build_comment'] = '# '
        d['noarch_python_comment'] = '# '

    with open(os.path.join(direc, 'meta.yaml'), 'w') as fid:
        fid.write(meta_template.format(**d))

    return direc, depends


def build_package(package, version=None, noarch_python=False):
    if ' ' in package:
        package, version = package.split(' ')
    try:
        directory = build_recipe(package, version=version)
        dependencies = convert_recipe(directory, package,
                                      noarch_python=noarch_python)
    except RuntimeError:
        directory, dependencies = make_recipe(package, version,
                                              noarch_python=noarch_python)

    return_code = 0

    try:
        print("package = %s" % package)
        print("   dependencies = %s" % dependencies)
        # Dependencies will be either package_name or
        #  package_name version_number
        # Only == dependency specs get version numbers
        # All else are just handled without a version spec
        for depend in dependencies:
            build_package(depend)
        args = build_template.format(directory).split()
        print("Building conda package for {0}".format(package.lower()))

        try:
            utils.execute(args, check_exit_code=True)
        except subprocess.CalledProcessError as exc:
            return_code = exc.return_code
        else:
            m = MetaData(directory)
            handle_binstar_upload(build.bldpkg_path(m))
    finally:
        rm_rf(directory)
    return return_code


def execute(args, parser):
    global binstar_upload
    global client
    binstar_upload = args.binstar_upload

    client = ServerProxy(args.pypi_url)
    package = args.pypi_name[0]
    if args.release == 'latest':
        version = None
        all_versions = False
    else:
        all_versions = True
        version = args.release[0]

    search = client.search({'name': package})
    if search:
        r_name = list(filter(lambda x: ('name' in x and package.lower() == x['name'].lower()), search))
        if r_name:
            print('Package search: %s' % r_name[0])
            package = r_name[0]['name']

    releases = client.package_releases(package, all_versions)
    if not releases:
        sys.exit("Error:  PyPI does not have a package named %s" % package)

    if all_versions and version not in releases:
        print(releases)
        print("Warning:  PyPI does not have version %s of package %s" %
              (version, package))

    if all_versions:
        build_package(package, version, noarch_python=args.noarch_python)
    else:
        version = releases[0]
        build_package(package, version, noarch_python=args.noarch_python)


if __name__ == '__main__':
    main()
