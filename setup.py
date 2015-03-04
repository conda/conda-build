#!/usr/bin/env python
import sys

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

import versioneer


if sys.version_info[:2] < (2, 7):
    sys.exit("conda is only meant for Python >=2.7"
             "Current Python version: %d.%d" % sys.version_info[:2])

versioneer.versionfile_source = 'conda_build/_version.py'
versioneer.versionfile_build = 'conda_build/_version.py'
versioneer.tag_prefix = ''
versioneer.parentdir_prefix = 'conda-build-'

setup(
    name = "conda-build",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author = "Continuum Analytics, Inc.",
    author_email = "ilan@continuum.io",
    url = "https://github.com/conda/conda-build",
    license = "BSD",
    classifiers = [
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
    ],
    description = "tools for building conda packages",
    long_description = open('README.rst').read(),
    packages = ['conda_build'],
    scripts = [
        'bin/conda-build',
        'bin/conda-convert',
        'bin/conda-index',
        'bin/conda-skeleton',
        'bin/conda-pipbuild',
        'bin/conda-metapackage',
        'bin/conda-develop',
        'bin/conda-inspect',
        ],
    install_requires = ['conda'],

    package_data={'conda_build': ['templates/*', 'cli-*.exe']},
)
