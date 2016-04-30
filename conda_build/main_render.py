# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
from collections import deque
from glob import glob
from locale import getpreferredencoding
import os
from os.path import exists, isdir, isfile, join, abspath

import yaml

from conda_build.config import config
from conda.compat import PY3
from conda.cli.common import add_parser_channels
from conda.cli.conda_argparse import ArgumentParser

from conda_build import __version__, exceptions
from conda_build.metadata import MetaData
import conda_build.source as source
from conda_build.completers import (all_versions, conda_version, RecipeCompleter, PythonVersionCompleter,
                                  RVersionsCompleter, LuaVersionsCompleter, NumPyVersionCompleter)
from conda_build.utils import find_recipe

on_win = (sys.platform == 'win32')


def get_render_parser():
    p = ArgumentParser(
        description="""
Tool for building conda packages. A conda package is a binary tarball
containing system-level libraries, Python modules, executable programs, or
other components. conda keeps track of dependencies between packages and
platform specifics, making it simple to create working environments from
        different sets of packages.""",
        conflict_handler='resolve'
    )
    p.add_argument(
        '-V', '--version',
        action='version',
        help='Show the conda-build version number and exit.',
        version = 'conda-build %s' % __version__,
    )
    p.add_argument(
        '-s', "--source",
        action="store_true",
        help="Obtain the source and fill in related template variables.",
    )
    p.add_argument(
        '--python',
        action="append",
        help="""Set the Python version used by conda build. Can be passed
        multiple times to build against multiple versions. Can be 'all' to
    build against all known versions (%r)""" % [i for i in
    PythonVersionCompleter() if '.' in i],
        metavar="PYTHON_VER",
        choices=PythonVersionCompleter(),
    )
    p.add_argument(
        '--perl',
        action="append",
        help="""Set the Perl version used by conda build. Can be passed
        multiple times to build against multiple versions.""",
        metavar="PERL_VER",
    )
    p.add_argument(
        '--numpy',
        action="append",
        help="""Set the NumPy version used by conda build. Can be passed
        multiple times to build against multiple versions. Can be 'all' to
    build against all known versions (%r)""" % [i for i in
    NumPyVersionCompleter() if '.' in i],
        metavar="NUMPY_VER",
        choices=NumPyVersionCompleter(),
    )
    p.add_argument(
        '--R',
        action="append",
        help="""Set the R version used by conda build. Can be passed
        multiple times to build against multiple versions.""",
        metavar="R_VER",
        choices=RVersionsCompleter(),
    )
    p.add_argument(
        '--lua',
        action="append",
        help="""Set the Lua version used by conda build. Can be passed
        multiple times to build against multiple versions (%r).""" % [i for i in LuaVersionsCompleter()],
        metavar="LUA_VER",
        choices=LuaVersionsCompleter(),
    )
    add_parser_channels(p)
    return p


def set_language_env_vars(args):
    """Given args passed into conda command, set language env vars"""
    for lang in all_versions:
        versions = getattr(args, lang)
        if not versions:
            continue
        if versions == ['all']:
            if all_versions[lang]:
                versions = all_versions[lang]
            else:
                parser.error("'all' is not supported for --%s" % lang)
        if len(versions) > 1:
            for ver in versions[:]:
                setattr(args, lang, [str(ver)])
                execute(args, parser)
                # This is necessary to make all combinations build.
                setattr(args, lang, versions)
            return
        else:
            version = versions[0]
            if lang in ('python', 'numpy'):
                version = int(version.replace('.', ''))
            setattr(config, conda_version[lang], version)
        if not len(str(version)) in (2, 3) and lang in ['python', 'numpy']:
            if all_versions[lang]:
                raise RuntimeError("%s must be major.minor, like %s, not %s" %
                    (conda_version[lang], all_versions[lang][-1]/10, version))
            else:
                raise RuntimeError("%s must be major.minor, not %s" %
                    (conda_version[lang], version))

    # Using --python, --numpy etc. is equivalent to using CONDA_PY, CONDA_NPY, etc.
    # Auto-set those env variables
    for var in conda_version.values():
        if hasattr(config, var):
            # Set the env variable.
            os.environ[var] = str(getattr(config, var))


def render_recipe(recipe_path, download_source=False):
    import shutil
    import tarfile
    import tempfile

    from conda.lock import Locked

    with Locked(config.croot):
        arg = recipe_path
        try_again = False
        # Don't use byte literals for paths in Python 2
        if not PY3:
            arg = arg.decode(getpreferredencoding() or 'utf-8')
        if isfile(arg):
            if arg.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
                recipe_dir = tempfile.mkdtemp()
                t = tarfile.open(arg, 'r:*')
                t.extractall(path=recipe_dir)
                t.close()
                need_cleanup = True
            else:
                print("Ignoring non-recipe: %s" % arg)
                return
        else:
            recipe_dir = abspath(arg)
            need_cleanup = False

        if not isdir(recipe_dir):
            sys.exit("Error: no such directory: %s" % recipe_dir)

        try:
            m = MetaData(recipe_dir)
        except exceptions.YamlParsingError as e:
            sys.stderr.write(e.error_msg())
            sys.exit(1)

        if download_source:
            source.provide(m.path, m.get_section('source'), patch=False)
            print('Source tree in:', source.get_dir())

        try:
            m.parse_again(permit_undefined_jinja=False)
        except SystemExit:
            # Something went wrong; possibly due to undefined GIT_ jinja variables.
            # Maybe we need to actually download the source in order to resolve the build_id.
            source.provide(m.path, m.get_section('source'))

            # Parse our metadata again because we did not initialize the source
            # information before.
            m.parse_again(permit_undefined_jinja=False)

            print(build.bldpkg_path(m))
            raise

        if need_cleanup:
            shutil.rmtree(recipe_dir)

    return m


# Next bit of stuff is to support YAML output in the order we expect.
# http://stackoverflow.com/a/17310199/1170370
class MetaYaml(dict):
    fields = ["package", "source", "build", "requirements", "test", "extra"]
    def to_omap(self):
        return [(field, self[field]) for field in MetaYaml.fields]


def represent_omap(dumper, data):
   return dumper.represent_mapping(u'tag:yaml.org,2002:map', data.to_omap())

def unicode_representer(dumper, uni):
    node = yaml.ScalarNode(tag=u'tag:yaml.org,2002:str', value=uni)
    return node


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(IndentDumper, self).increase_indent(flow, False)


yaml.add_representer(MetaYaml, represent_omap)
if PY3:
    yaml.add_representer(str, unicode_representer)
else:
    yaml.add_representer(unicode, unicode_representer)


def main():
    import pprint
    p = get_render_parser()
    p.add_argument(
        '-y', '--yaml',
        action="store_true",
        help="print YAML, as opposed to printing the metadata as a dictionary"
    )
    # we do this one separately because we only allow one entry to conda render
    p.add_argument(
        'recipe',
        action="store",
        metavar='RECIPE_PATH',
        choices=RecipeCompleter(),
        help="Path to recipe directory.",
    )

    args = p.parse_args()
    set_language_env_vars(args)

    metadata = render_recipe(find_recipe(args.recipe), download_source=args.source)
    if args.yaml:
        print(yaml.dump(MetaYaml(metadata.meta), Dumper=IndentDumper,
                        default_flow_style=False, indent=4))
    else:
        pprint.pprint(metadata.meta)


if __name__ == '__main__':
    main()
