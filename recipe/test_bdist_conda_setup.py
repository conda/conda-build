from setuptools import setup
import conda_build.bdist_conda

setup(
    name="package",
    version="1.0.0",
    distclass=conda_build.bdist_conda.CondaDistribution,
)
