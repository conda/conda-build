import os
from setuptools import setup

if not os.getenv("CONDA_BUILD_STATE") == "RENDER":
    raise ValueError("Conda build state not set correctly")

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
    ],
    description="test package for testing conda-build",
    packages=['conda_build_test'],
    scripts=[
        'bin/test-script-setup.py',
    ],
)
