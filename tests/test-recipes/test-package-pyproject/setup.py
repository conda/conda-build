import sys
from setuptools import setup
# from distutils.core import setup

# test with an old version of Python that we'll never normally use
if sys.version_info[:2] == (3, 5):
    # die intentionally to signal that we're using the old python version
    sys.exit(1)

setup()
