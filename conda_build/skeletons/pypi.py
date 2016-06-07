from conda.cli.common import Completer
from conda.config import default_python

class PyPIPackagesCompleter(Completer):
    def __init__(self, prefix, parsed_args, **kwargs):
        self.prefix = prefix
        self.parsed_args = parsed_args

    def _get_items(self):
        from conda_build.pypi import get_xmlrpc_client
        args = self.parsed_args
        client = get_xmlrpc_client(getattr(args, 'pypi_url'))
        return [i.lower() for i in client.list_packages()]

pypi_example = """
Examples:

Create a recipe for the sympy package:

    conda skeleton pypi sympy

Create a recipes for the flake8 package and all its dependencies:

    conda skeleton pypi --recursive flake8

Use the --pypi-url flag to point to a PyPI mirror url:

    conda skeleton pypi --pypi-url <mirror-url> package_name
"""

def add_parser(repos):
    """Modify repos in place, adding the PyPI option"""
    pypi = repos.add_parser(
        "pypi",
        help="""
    Create recipe skeleton for packages hosted on the Python Packaging Index
    (PyPI) (pypi.python.org).
        """,
        epilog=pypi_example,
    )
    pypi.add_argument(
        "packages",
        action="store",
        nargs='+',
        help="""PyPi packages to create recipe skeletons for.
                You can also specify package[extra,...] features.""",
    ).completer = PyPIPackagesCompleter
    pypi.add_argument(
        "--output-dir",
        action="store",
        nargs=1,
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    pypi.add_argument(
        "--version",
        action="store",
        nargs=1,
        help="Version to use. Applies to all packages.",
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
        default='https://pypi.io/pypi',
        help="URL to use for PyPI (default: %(default)s).",
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
        "--all-extras",
        action="store_true",
        default=False,
        help="Add all extra feature requirements. Applies to all packages.",
    )
    pypi.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist.'
    )
    pypi.add_argument(
        "--version-compare",
        action='store_true',
        help="""Compare the package version of the recipe with the one available
        on PyPI."""
    )
    pypi.add_argument(
        "--python-version",
        action='store',
        default=default_python,
        help="""Version of Python to use to run setup.py. Default is %(default)s.""",
        choices=['2.7', '3.4', '3.5'],
    )

    pypi.add_argument(
        "--manual-url",
        action='store_true',
        default=False,
        help="Manually choose source url when more than one urls are present." +
                "Default is the one with least source size."
    )

    pypi.add_argument(
        "--noarch-python",
        action='store_true',
        default=False,
        help="Creates recipe as noarch python"
    )
