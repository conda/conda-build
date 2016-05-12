# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys

import yaml

from conda.compat import PY3
from conda.cli.common import add_parser_channels
from conda.cli.conda_argparse import ArgumentParser

from conda_build import __version__
from conda_build.build import bldpkg_path
from conda_build.render import render_recipe, set_language_env_vars
from conda_build.utils import find_recipe
from conda_build.completers import (RecipeCompleter, PythonVersionCompleter, RVersionsCompleter,
                                    LuaVersionsCompleter, NumPyVersionCompleter)

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
        version='conda-build %s' % __version__,
    )
    p.add_argument(
        '-n', "--no_source",
        action="store_true",
        help="When templating can't be completed, do not obtain the \
source to try fill in related template variables.",
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="Output the conda package filename which would have been "
               "created",
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
        help="Set the Lua version used by conda build. Can be passed"
        "multiple times to build against multiple versions (%r)." %
        [i for i in LuaVersionsCompleter()],
        metavar="LUA_VER",
        choices=LuaVersionsCompleter(),
    )
    add_parser_channels(p)
    return p


# Next bit of stuff is to support YAML output in the order we expect.
# http://stackoverflow.com/a/17310199/1170370
class MetaYaml(dict):
    fields = ["package", "source", "build", "requirements", "test", "about", "extra"]

    def to_omap(self):
        return [(field, self[field]) for field in MetaYaml.fields if field in self]


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
    unicode = None  # silence pyflakes about unicode not existing in py3
else:
    yaml.add_representer(unicode, unicode_representer)


def main():
    p = get_render_parser()
    p.add_argument(
        '-f', '--file',
        action="store",
        help="write YAML to file, given as argument here.\
              Overwrites existing files."
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
    set_language_env_vars(args, p)

    metadata = render_recipe(find_recipe(args.recipe), no_download_source=args.no_source)
    if args.output:
        print(bldpkg_path(metadata))
    else:
        output = yaml.dump(MetaYaml(metadata.meta), Dumper=IndentDumper,
                            default_flow_style=False, indent=4)
        if args.file:
            with open(args.file, "w") as f:
                f.write(output)
        else:
            print(output)


if __name__ == '__main__':
    main()
