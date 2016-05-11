#!/usr/bin/env python
import sys
from glob import glob

import versioneer

if 'develop' in sys.argv:
    from setuptools import setup
else:
    from distutils.core import setup

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
    author_email="ilan@continuum.io",
    url="https://github.com/conda/conda-build",
    license="BSD",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
    ],
    description="tools for building conda packages",
    long_description=open('README.rst').read(),
    packages=['conda_build'],
    scripts=glob('bin/*'),
    install_requires=['conda'],
    package_data={'conda_build': ['templates/*', 'cli-*.exe']},
)
