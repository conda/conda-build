==============
Sample recipes
==============

Conda offers you the flexibility of being able to build things
that are not Python related. The first 2 sample recipes,
``boost`` and ``libtiff``, are examples of non-Python libraries, meaning
they do not require Python to run or build.

* `boost <https://github.com/AnacondaRecipes/boost-feedstock>`_ is an example
  of a popular programming library and illustrates the use of selectors in a recipe.

* `libtiff <https://github.com/AnacondaRecipes/libtiff-feedstock>`_ is
  another example of a compiled library, which shows how conda can apply patches to source directories before building the package.

* `msgpack <https://github.com/AnacondaRecipes/msgpack-python-feedstock>`_,
  `blosc <https://github.com/AnacondaRecipes/python-blosc-feedstock>`_, and
  `cytoolz <https://github.com/AnacondaRecipes/cytoolz-feedstock>`_
  are examples of Python libraries with extensions.

* `toolz <https://github.com/AnacondaRecipes/toolz-feedstock>`_,
  `sympy <https://github.com/AnacondaRecipes/sympy-feedstock>`_,
  `six <https://github.com/AnacondaRecipes/six-feedstock>`_, and
  `gensim <https://github.com/AnacondaRecipes/gensim-feedstock>`_ are
  examples of Python-only libraries.

``gensim`` works on Python 2, and all of the others work on both Python 2 and Python 3.
