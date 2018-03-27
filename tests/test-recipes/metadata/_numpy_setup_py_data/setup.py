import setuptools
import numpy.distutils.core
from Cython.Build import cythonize

requirements = [
    "numpy>=1.9.0",
    ]

numpy.distutils.core.setup(
    author = "Bill Ladwig",
    author_email = "ladwig@ucar.edu",
    description = "Test case for conda-build crash",
    url = "https://github.com/NCAR/load_setup_py_test",
    install_requires = requirements,
    name = "fortest",
    version =  "0.1.0",
    package_dir = {"" : "src"},
    scripts=[]
)
