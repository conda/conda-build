from distutils.core import setup
import os

if "CONDA_BUILD_RENDERING" in os.environ:
    print("Rendering environment variable set OK")

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
    ],
    description="test package for testing conda-build",
    packages=['conda_build_test'],
    scripts=[
        'bin/test-script-setup.py',
    ],
)
