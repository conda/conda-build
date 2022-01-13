from distutils.core import setup
import distutils.command.bdist_conda

setup(
    name="conda-build-test-project",
    version='1.0',
    distclass=distutils.command.bdist_conda.CondaDistribution,
    conda_buildnum=1,
    conda_features=[],
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
