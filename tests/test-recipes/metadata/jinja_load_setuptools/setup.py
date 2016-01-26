from distutils.core import setup

VERSION = '1.test'


def version_func():
    # ensure we can look up globals from function scope
    return VERSION


setup(
    name="conda-build-load_setuptools",
    version=version_func(),
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
    packages=['../../test-package/conda_build_test'],
    scripts=[
        '../../test-package/bin/test-script-setup.py',
    ],
    test_attr=version_func(),
)
