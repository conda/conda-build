from __future__ import absolute_import, division, print_function

import versioneer
from setuptools import setup, find_packages

setup(
    name="{{ name }}",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author="{{ author }}",
    author_email="{{ email }}",
    description="{{ name }}",
    packages=find_packages(exclude=['tests']),
    long_description=open('README.rst').read() if exists('README.rst') else '',)
