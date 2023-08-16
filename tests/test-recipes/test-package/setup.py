import sys
from setuptools import setup

# test with an old version of Python that we'll never normally use
if sys.version_info[:2] == (3, 5):
    # die intentionally to signal that we're using the old python version
    sys.exit(1)

setup(
    name="conda-build-test-project",
    version='1.0',
    author="Continuum Analytics, Inc.",
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
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    description="test package for testing conda-build",
    packages=['conda_build_test'],
    scripts=[
        'bin/test-script-setup.py',
    ],
)
