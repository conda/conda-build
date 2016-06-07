def add_parser(repos):
    luarocks = repos.add_parser(
        "luarocks",
        help="""
    Create recipe skeleton for luarocks, hosted at luarocks.org
        """,
    )
    luarocks.add_argument(
        "packages",
        action="store",
        nargs='+',
        help="luarocks packages to create recipe skeletons for.",
    )
    luarocks.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    luarocks.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )
    luarocks.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist.')
