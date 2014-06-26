"""
bdist_conda

"""
from __future__ import (print_function, division, unicode_literals,
    absolute_import)

from distutils.core import Command

class bdist_conda(Command):
    description = "create a conda package"

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        pass
