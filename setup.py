#!/usr/bin/env python
import sys

import versioneer

from setuptools import setup

if sys.version_info[:2] < (2, 7):
    sys.exit("conda-build is only meant for Python >=2.7"
             "Current Python version: %d.%d" % sys.version_info[:2])

versioneer.VCS = 'git'
versioneer.versionfile_source = 'conda_build/_version.py'
versioneer.versionfile_build = 'conda_build/_version.py'
versioneer.tag_prefix = ''
versioneer.parentdir_prefix = 'conda-build-'

setup(
    name="conda-build",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author="Continuum Analytics, Inc.",
    author_email="conda@continuum.io",
    url="https://github.com/conda/conda-build",
    license="BSD 3-clause",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
    ],
    description="tools for building conda packages",
    long_description=open('README.rst').read(),
    packages=['conda_build', 'conda_build.cli',
              'conda_build.skeletons', 'conda_build.os_utils'],
    entry_points={
        'console_scripts': ['conda-build = conda_build.cli.main_build:main',
                            'conda-convert = conda_build.cli.main_convert:main',
                            'conda-develop = conda_build.cli.main_develop:main',
                            'conda-index = conda_build.cli.main_index:main',
                            'conda-inspect = conda_build.cli.main_inspect:main',
                            'conda-metapackage = conda_build.cli.main_metapackage:main',
                            'conda-render = conda_build.cli.main_render:main',
                            'conda-sign = conda_build.cli.main_sign:main',
                            'conda-skeleton = conda_build.cli.main_skeleton:main',
                            ]},
    install_requires=['conda', 'requests'],
    package_data={'conda_build': ['templates/*', 'cli-*.exe']},
    zip_safe=False,
)
