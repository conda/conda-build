def add_parser(repos):
    cpan = repos.add_parser(
        "cpan",
        help="""
    Create recipe skeleton for packages hosted on the Comprehensive Perl Archive
    Network (CPAN) (cpan.org).
        """,
    )
    cpan.add_argument(
        "packages",
        action="store",
        nargs='+',
        help="CPAN packages to create recipe skeletons for.",
    )
    cpan.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    cpan.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )
    cpan.add_argument(
        "--meta-cpan-url",
        action="store",
        nargs=1,
        default='http://api.metacpan.org',
        help="URL to use for MetaCPAN API.",
    )
    cpan.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist.')
