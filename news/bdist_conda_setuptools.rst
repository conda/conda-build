Enhancements:
-------------

* <news item>

Bug fixes:
----------

* Enable bdist_conda via entry_point mechanism supported also by setuptools >=60.0.0.
  Usable via `from setuptools import setup` and `setup(distclass=conda_build.bdist_conda.CondaDistribution, ...)`.

Deprecations:
-------------

* Usage of bdist_conda via `from distutils.core import setup` and `distclass=distutils.command.bdist_conda.CondaDistribution`,
  as that only works for setuptools <60.0.0.

Docs:
-----

* <news item>

Other:
------

* <news item>
