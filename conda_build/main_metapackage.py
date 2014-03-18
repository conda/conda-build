# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import os

import conda.config

from conda_build.metadata import MetaData
from conda_build.build import create_info_files
from conda_build.utils import rm_rf
import conda_build.config

def main():
    p = argparse.ArgumentParser(
        description='''tool for building conda metapackages. A metapackage is a
    package with no files, only metadata'''
    )

    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help="do not ask to upload the package to binstar",
        dest='binstar_upload',
        default=conda.config.binstar_upload,
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="output the conda package filename which would have been "
               "created and exit",
    )
    p.add_argument(
        "name",
        action="store",
        help="name of the created package",
    )
    p.add_argument(
        "version",
        action="store",
        help="version of the created package",
    )
    p.add_argument(
        "--build-number",
        action="store",
        type=int,
        default=0,
        help="build number for the package (default is 0)",
    )
    p.add_argument(
        "--build-string",
        action="store",
        default=None,
        help="build string for the package (default is automatically generated)",
    )
    p.add_argument(
        "--dependencies", "-d",
        nargs='*',
        default=(),
        help="""The dependencies of the package. To specify a version
        restriction for a dependency, wrap the dependency in quotes, like
        'package >=2.0'""",
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args.func(args, p)

def execute(args, parser):
    d = {'package': {}, 'build': {}, 'requirements': {}}
    d['package']['name'] = args.name
    d['package']['version'] = args.version
    d['build']['number'] = args.build_number
    # MetaData does the auto stuff if the build string is None
    d['build']['string'] = args.build_string
    d['requirements']['run'] = args.dependencies
    m = MetaData.fromdict(d)

    prefix = conda_build.config.build_prefix
    rm_rf(prefix)
    os.makedirs(prefix)
    create_info_files(m, [], include_recipe=False)

if __name__ == '__main__':
    main()
