# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""This file is an example of the structure that any add-on module for a new language should have.

You can have structure beyond this, but this is a minimum of what conda-build will look for."""


def package_exists(package_name):
    """This is a simple function returning True/False for if a requested package string exists
    in the add-on repository."""
    return package_name == "frank"


def skeletonize(packages, output_dir="."):
    """This is the main work function that coordinates retrieval of the foreign recipe and outputs
    the conda recipe skeleton.

    Arguments here should match the arguments for the parser below."""
    print(packages)
    print(output_dir)


def add_parser(repos):
    """Adds a parser entry so that your addition shows up as

    conda skeleton my_repo

    And also provides the arguments that your parser accepts.
    """
    my_repo = repos.add_parser(
        "my_repo",
        help="""
    Create recipe skeleton for packages hosted on my-repo.org
        """,
    )
    my_repo.add_argument(
        "packages",
        nargs="+",
        help="my-repo packages to create recipe skeletons for.",
    )

    # Add any additional parser arguments here

    return None
