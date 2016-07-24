# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse

import conda.config
from conda.cli.conda_argparse import ArgumentParser

from conda_build import api
from conda_build.config import Config
from conda_build.cli.main_build import args_func


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
        dest='anaconda_upload',
        default=conda.config.binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest='anaconda_upload',
        default=conda.config.binstar_upload,
    )
    p.add_argument(
        "name",
        help="Name of the created package.",
    )
    p.add_argument(
        "version",
        help="Version of the created package.",
    )
    p.add_argument(
        "--build-number",
        type=int,
        default=0,
        help="Build number for the package (default is 0).",
    )
    p.add_argument(
        "--build-string",
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
        help="The homepage for the metapackage."
    )
    p.add_argument(
        "--license",
        help="The license of the metapackage.",
    )
    p.add_argument(
        "--summary",
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
    args_func(args, p, config=Config(**args.__dict__))


def execute(args, parser, config):
    api.create_metapackage(name=args.name, version=args.version, entry_points=args.entry_points,
                           build_string=args.build_string, build_number=args.build_number,
                           dependencies=args.dependencies, home=args.home, license=args.license,
                           summary=args.summary)


if __name__ == '__main__':
    main()
