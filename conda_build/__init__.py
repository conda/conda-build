# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause

try:
    from ._version import __version__
except ImportError:
    # _version.py is only created after running `pip install`
    try:
        from setuptools_scm import get_version

        __version__ = get_version(root="..", relative_to=__file__)
    except (ImportError, OSError, LookupError):
        # ImportError: setuptools_scm isn't installed
        # OSError: git isn't installed
        # LookupError: setuptools_scm unable to detect version
        # Conda-build abides by CEP-8 which specifies using CalVer, so the dev version is:
        #     YY.MM.MICRO.devN+gHASH[.dirty]
        __version__ = "0.0.0.dev0+placeholder"

__all__ = ["__version__"]

# Sub commands added by conda-build to the conda command
sub_commands = [
    "build",
    "convert",
    "develop",
    "index",
    "inspect",
    "metapackage",
    "render",
    "skeleton",
]

# Skip context logic for doc generation since we don't install all dependencies in the CI doc build environment,
# see .readthedocs.yml file
try:
    import os

    from conda.base.context import reset_context

    # Disallow softlinks. This avoids a lot of dumb issues, at the potential cost of disk space.
    os.environ["CONDA_ALLOW_SOFTLINKS"] = "false"
    reset_context()

except ImportError:
    pass
