# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse

from conda.config import default_python

def main():
    p = argparse.ArgumentParser(
        description='create skeleton recipes for packages from hosting sites'
    )

    repos = p.add_subparsers(
        dest="repo"
    )

    pypi = repos.add_parser(
        "pypi",
        help="Create recipes from packages on PyPI",
    )
    pypi.add_argument(
        "packages",
        action="store",
        nargs='+',
        help="PyPi packages to create recipe skeletons for",
    )
    pypi.add_argument(
        "--output-dir",
        action="store",
        nargs=1,
        help="Directory to write recipes to",
        default=".",
    )
    pypi.add_argument(
        "--version",
        action="store",
        nargs=1,
        help="Version to use. Applies to all packages",
    )
    pypi.add_argument(
        "--all-urls",
        action="store_true",
        help="""Look at all URLs, not just source URLs. Use this if it can't
                find the right URL.""",
    )
    pypi.add_argument(
        "--pypi-url",
        action="store",
        nargs=1,
        default='https://pypi.python.org/pypi',
        help="URL to use for PyPI",
    )
    pypi.add_argument(
        "--no-download",
        action="store_false",
        dest="download",
        default=True,
        help="""Don't download the package. This will keep the recipe from
                finding the right dependencies and entry points if the package
                uses distribute.  WARNING: The default option downloads and runs
                the package's setup.py script."""
    )
    pypi.add_argument(
        "--no-prompt",
        action="store_true",
        default=False,
        dest="noprompt",
        help="""Don't prompt the user on ambiguous choices.  Instead, make the
        best possible choice and continue."""
    )
    pypi.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist.'
    )
    pypi.add_argument(
        "--python-version",
        action='store',
        default=default_python,
        help="""Version of Python to use to run setup.py. Default is %(default)s.""",
        choices=['2.6', '2.7', '3.3', '3.4'],
        )

    cpan = repos.add_parser(
        "cpan",
        help="Create recipes from packages on CPAN",
    )
    cpan.add_argument(
        "packages",
        action="store",
        nargs='+',
        help="CPAN packages to create recipe skeletons for",
    )
    cpan.add_argument(
        "--output-dir",
        help="Directory to write recipes to",
        default=".",
    )
    cpan.add_argument(
        "--version",
        help="Version to use. Applies to all packages",
    )
    cpan.add_argument(
        "--meta-cpan-url",
        action="store",
        nargs=1,
        default='http://api.metacpan.org',
        help="URL to use for MetaCPAN API",
    )
    cpan.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist.')

    p.set_defaults(func=execute)

    args = p.parse_args()
    args.func(args, p)


def execute(args, parser):
    import conda_build.pypi as pypi
    import conda_build.cpan as cpan
    from conda.lock import Locked
    from conda_build.config import croot

    with Locked(croot):
        if args.repo == "pypi":
            pypi.main(args, parser)
        elif args.repo == "cpan":
            cpan.main(args, parser)


if __name__ == '__main__':
    main()
