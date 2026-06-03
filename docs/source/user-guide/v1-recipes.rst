****************************************
Building v1 recipes with conda-build
****************************************

``conda-build`` now supports building v1 recipes using the
`Python bindings for rattler-build <https://rattler-build.prefix.dev/latest/py-rattler-build/reference/>`_.

To get started with building v1 recipes, simply invoke ``conda-build`` and pass
the recipe's directory. ``conda-build`` will recognize the recipe format and
handle the build through ``py-rattler-build``.

``conda-build`` currently supports v1 recipes in the ``conda build`` and
``conda render`` commands.

Build configuration is done in the same way as for v0 recipes. Many configuration settings are translated into rattler-build equivalents and
passed to ``py-rattler-build``. The following command-line arguments (and their corresponding settings in ``~/.condarc`` file) are
supported:

``conda build``
===============

- ``--recipe``
- ``--build-only``
- ``--variant-config-files``
- ``--exclusive-config-file``
- ``--extra-meta``
- ``--output-folder``
- ``--no-build-id``
- ``--debug``
- ``--notest``
- ``--quiet``
- ``--skip-existing``
- ``--no-include-recipe``
- ``--package-format``
- ``--zstd-compression-level``
- ``--channel``
- ``--override-channels``
- ``--post``
- ``--anaconda-upload``
- ``--anaconda-token``
- ``--user``

``conda render``
================

- ``--recipe``
- ``--variant-config-files``
- ``--exclusive-config-file``
- ``--override-channels``

Package upload
==============

Packages built from v1 recipes can be uploaded in the same way as those built
from v0 recipes. ``conda-build`` will automatically upload packages to the
specified anaconda.org channel if this option is enabled in ``.condarc`` or
through the ``conda-build`` CLI.

Limitations
===========

Limitations of the current v1 recipe implementation include:

- UI improvements: currently, ``conda-build`` uses a modified version of
  rattler-build's ``SimpleProgressCallback`` to pass levels and messages to
  ``conda-build``'s logging system. This can be updated in the future to improve the look
  and be more consistent with rattler-build itself.
- Support for multichannels is not complete. If set, ``conda-build`` currently
  expands the subchannels from a multichannel and passes them to
  ``py-rattler-build`` which may not respect the channel priority. This will be updated once ``rattler-build`` gains proper `support
  for multichannels <https://github.com/conda/rattler/issues/1327>`_.

Migrating recipes
=================

Migrating recipes to v1 format is recommended because it provides faster rendering and buiding, standardized schema with autocomplete support and pure YAML syntax, which guarantees easier updates in future.

To migrate a recipe from v0 to v1 format, use the `conda-recipe-manager <https://github.com/conda/conda-recipe-manager>`_ tool.

Running::

  conda-recipe-manager convert recipe/meta.yaml > recipe/recipe.yaml

will convert and write the recipe to the ``recipe.yaml`` file.

There are some differences between the v0 and v1 recipe formats, so extra care is
required when converting. Some of these differences are explained in
the
`rattler-build documentation <https://rattler-build.prefix.dev/dev/converting_from_conda_build/>`_.

More details about the v1 recipe format can be found in the two CEPs:

- `CEP-0013 <https://github.com/conda/ceps/blob/main/cep-0013.md>`_
- `CEP-0014 <https://github.com/conda/ceps/blob/main/cep-0014.md>`_
