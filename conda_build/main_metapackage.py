# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse
from collections import defaultdict

import conda.config
from conda.cli.conda_argparse import ArgumentParser

from conda_build.main_build import args_func
from conda_build.metadata import MetaData
from conda_build.build import build, bldpkg_path
from conda_build.main_build import handle_binstar_upload


def main():
    p = ArgumentParser(
        description='''
Tool for building conda metapackages.  A metapackage is a package with no
files, only metadata.  They are typically used to collect several packages
together into a single package via dependencies.

NOTE: Metapackages can also be created by creating a recipe with the necessary
metadata in the meta.yaml, but a metapackage can be created entirely from the
command line with the conda metapackage command.
''',
    )

    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest='binstar_upload',
        default=conda.config.binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest='binstar_upload',
        default=conda.config.binstar_upload,
    )
    p.add_argument(
        '--token',
        help="Token to pass through to anaconda upload"
    )
    p.add_argument(
        '--user',
        help="User/organization to upload packages to on anaconda.org"
    )
    p.add_argument(
        "name",
        action="store",
        help="Name of the created package.",
    )
    p.add_argument(
        "version",
        action="store",
        help="Version of the created package.",
    )
    p.add_argument(
        "--build-number",
        action="store",
        type=int,
        default=0,
        help="Build number for the package (default is 0).",
    )
    p.add_argument(
        "--build-string",
        action="store",
        default=None,
        help="Build string for the package (default is automatically generated).",
    )
    p.add_argument(
        "--dependencies", "-d",
        nargs='*',
        default=(),
        help="""The dependencies of the package. To specify a version restriction for a
        dependency, wrap the dependency in quotes, like 'package >=2.0'.""",
    )
    p.add_argument(
        "--home",
        action="store",
        help="The homepage for the metapackage."
    )
    p.add_argument(
        "--license",
        action="store",
        help="The license of the metapackage.",
    )
    p.add_argument(
        "--summary",
        action="store",
        help="""Summary of the package.  Pass this in as a string on the command
        line, like --summary 'A metapackage for X'. It is recommended to use
        single quotes if you are not doing variable substitution to avoid
        interpretation of special characters.""",
    )
    p.add_argument(
        "--entry-points",
        nargs='*',
        default=(),
        help="""Python entry points to create automatically. They should use the same
        syntax as in the meta.yaml of a recipe, e.g., --entry-points
        bsdiff4=bsdiff4.cli:main_bsdiff4 will create an entry point called
        bsdiff4 that calls bsdiff4.cli.main_bsdiff4(). """,
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def execute(args, parser):
    d = defaultdict(dict)
    d['package']['name'] = args.name
    d['package']['version'] = args.version
    d['build']['number'] = args.build_number
    d['build']['entry_points'] = args.entry_points
    # MetaData does the auto stuff if the build string is None
    d['build']['string'] = args.build_string
    d['requirements']['run'] = args.dependencies
    d['about']['home'] = args.home
    d['about']['license'] = args.license
    d['about']['summary'] = args.summary
    d = dict(d)
    m = MetaData.fromdict(d)

    build(m)
    handle_binstar_upload(bldpkg_path(m), args)

if __name__ == '__main__':
    main()
