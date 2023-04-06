#!/usr/bin/env python
# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from pathlib import Path

from setuptools import setup

import versioneer

# Don't proceed with 'unknown' in version
version_dict = versioneer.get_versions()
if version_dict["error"]:
    raise RuntimeError(version_dict["error"])

deps = [
    "conda",
    "requests",
    "filelock",
    "pyyaml",
    "jinja2",
    "pkginfo",
    "beautifulsoup4",
    "chardet",
    "pytz",
    "tomli",
    "tqdm",
    "psutil",
    "six",
    "libarchive-c",
    "packaging",
    # "conda-package-handling",  # remove comment once released on PyPI
    "glob2",
]

# We cannot build lief for Python 2.7 on Windows (unless we use mingw-w64 for it, which
# would be a non-trivial amount of work).
# .. lief is missing the egg-info directory so we cannot do this .. besides it is not on
# pypi.
# if sys.platform != 'win-32' or sys.version_info >= (3, 0):
#     deps.extend(['lief'])

setup(
    name="conda-build",
    version=version_dict["version"],
    cmdclass=versioneer.get_cmdclass(),
    author="Continuum Analytics, Inc.",
    author_email="conda@continuum.io",
    url="https://github.com/conda/conda-build",
    license="BSD-3-Clause",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires=">=3.8",
    description="tools for building conda packages",
    long_description=Path("README.md").read_text(),
    packages=[
        "conda_build",
        "conda_build.cli",
        "conda_build.skeletons",
        "conda_build.os_utils",
    ],
    entry_points={
        "console_scripts": [
            "conda-build = conda_build.cli.main_build:main",
            "conda-convert = conda_build.cli.main_convert:main",
            "conda-develop = conda_build.cli.main_develop:main",
            "conda-index = conda_build.cli.main_index:main",
            "conda-inspect = conda_build.cli.main_inspect:main",
            "conda-metapackage = conda_build.cli.main_metapackage:main",
            "conda-render = conda_build.cli.main_render:main",
            "conda-skeleton = conda_build.cli.main_skeleton:main",
            "conda-debug = conda_build.cli.main_debug:main",
        ],
        "distutils.commands": [
            "bdist_conda = conda_build.bdist_conda:bdist_conda",
        ],
    },
    install_requires=deps,
    package_data={"conda_build": ["templates/*", "cli-*.exe"]},
    zip_safe=False,
)
