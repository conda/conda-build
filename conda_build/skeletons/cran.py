from conda.cli.common import Completer

from conda_build.cran import get_cran_metadata


class CRANPackagesCompleter(Completer):
    def __init__(self, prefix, parsed_args, **kwargs):
        self.prefix = prefix
        self.parsed_args = parsed_args

    def _get_items(self):
        args = self.parsed_args
        cran_url = getattr(args, 'cran_url', 'http://cran.r-project.org/')
        output_dir = getattr(args, 'output_dir', '.')
        cran_metadata = get_cran_metadata(cran_url, output_dir, verbose=False)
        return [i.lower() for i in cran_metadata] + ['r-%s' % i.lower() for i
            in cran_metadata]


def add_parser(repos):
    cran = repos.add_parser(
        "cran",
        help="""
    Create recipe skeleton for packages hosted on the Comprehensive R Archive
    Network (CRAN) (cran.r-project.org).
        """,
    )
    cran.add_argument(
        "packages",
        action="store",
        nargs='*',
        help="""CRAN packages to create recipe skeletons for.""",
    ).completer = CRANPackagesCompleter
    cran.add_argument(
        "--output-dir",
        action="store",
        nargs=1,
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    cran.add_argument(
        "--version",
        action="store",
        nargs=1,
        help="Version to use. Applies to all packages.",
    )
    cran.add_argument(
        "--git-tag",
        action="store",
        nargs=1,
        help="Git tag to use for GitHub recipes.",
    )
    cran.add_argument(
        "--all-urls",
        action="store_true",
        help="""Look at all URLs, not just source URLs. Use this if it can't
                find the right URL.""",
    )
    cran.add_argument(
        "--cran-url",
        action="store",
        default='http://cran.r-project.org/',
        help="URL to use for CRAN (default: %(default)s).",
    )
    cran.add_argument(
        "--recursive",
        action='store_true',
        dest='recursive',
        help='Create recipes for dependencies if they do not already exist.',
    )
    cran.add_argument(
        "--no-recursive",
        action='store_false',
        dest='recursive',
        help="Don't create recipes for dependencies if they do not already exist.",
    )
    cran.add_argument(
        '--no-archive',
        action='store_false',
        dest='archive',
        help="Don't include an Archive download url.",
    )
    cran.add_argument(
        "--version-compare",
        action='store_true',
        help="""Compare the package version of the recipe with the one available
        on CRAN. Exits 1 if a newer version is available and 0 otherwise."""
    )
    cran.add_argument(
        "--update-outdated",
        action="store_true",
        help="""Update outdated packages in the output directory (set by
        --output-dir).  If packages are given, they are updated; otherwise, all
        recipes in the output directory are updated.""",
    )
