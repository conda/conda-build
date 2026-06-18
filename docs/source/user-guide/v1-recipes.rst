****************************************
Building v1 recipes with conda-build
****************************************

``conda-build`` now supports building v1 recipes using the
`Python bindings for rattler-build <https://rattler-build.prefix.dev/latest/py-rattler-build/reference/>`__.

To get started with building v1 recipes, simply invoke ``conda-build`` and pass
the recipe's directory. ``conda-build`` will recognize the recipe format and
handle the build through ``py-rattler-build``.

``conda-build`` currently supports v1 recipes in the ``conda build`` and
``conda render`` commands.

Build configuration is done in the same way as for v0 recipes. Many configuration settings are translated into rattler-build equivalents and
passed to ``py-rattler-build``. The following ``conda-build`` command-line arguments (and their corresponding settings in ``~/.condarc`` file) are
supported:

``conda build``
===============

- ``--anaconda-token``
- ``--anaconda-upload``
- ``--build-only``
- ``--channel``
- ``--debug``
- ``--exclusive-config-file``
- ``--extra-meta``
- ``--no-build-id``
- ``--no-include-recipe``
- ``--notest``
- ``--output-folder``
- ``--override-channels``
- ``--package-format``
- ``--post``
- ``--quiet``
- ``--recipe``
- ``--skip-existing``
- ``--user``
- ``--variant-config-files``
- ``--zstd-compression-level``

``conda render``
================

- ``--exclusive-config-file``
- ``--override-channels``
- ``--recipe``
- ``--variant-config-files``

Package upload
==============

Packages built from v1 recipes can be uploaded in the same way as those built
from v0 recipes. ``conda-build`` will automatically upload packages to the
specified anaconda.org channel if ``anaconda_upload`` is enabled in ``.condarc`` or
through the ``conda-build`` CLI.

Authentication with private channels
=====================================

For v1 recipes, ``conda-build`` uses rattler mechanism for private channel authentication.


`rattler-build documentation <https://rattler-build.prefix.dev/dev/authentication_and_upload/>`__
describes authentication with the following services:

- prefix.dev
- anaconda.org
- quetz
- artifactory
- s3


Authentication can be configured in one of two ways:

- Use the ``rattler-build auth login`` command.
- Set the ``RATTLER_AUTH_FILE`` environment variable to point to a JSON file
  containing credentials.

For example, to authenticate with a private channel hosted on ``prefix.dev``:

.. code-block:: bash

   echo '{"prefix.dev": {"BearerToken": "pfx-xxxxxxxx"}}' > ./credentials.json
   export RATTLER_AUTH_FILE=./credentials.json

After this setup, ``conda-build`` will be able to access packages hosted on the
private channel.


Limitations
===========

Limitations of the current v1 recipe implementation include:

- ``conda-build`` logs ``py-rattler-build`` reports in a simplified way.
  Decorative elements seen in ``rattler-build`` are not currently available.
- Support for multichannels is not complete. If set, ``conda-build`` currently
  expands the subchannels from a multichannel and passes them to
  ``py-rattler-build`` which may not respect the channel priority. This will be updated once ``rattler-build`` gains proper `support
  for multichannels <https://github.com/conda/rattler/issues/1327>`__.

Migrating recipes
=================

Migrating recipes to v1 format can be beneficial because it provides faster
rendering and buiding, standardized schema with autocomplete support,
and pure YAML syntax, which guarantees easier updates in the future.

To migrate a recipe from v0 to v1 format, use the `conda-recipe-manager <https://github.com/conda/conda-recipe-manager>`__ tool.

Running::

  conda-recipe-manager convert recipe/meta.yaml > recipe/recipe.yaml

will convert and write the recipe to the ``recipe.yaml`` file.

There are some differences between the v0 and v1 recipe formats, so extra care is
required when converting. Some of these differences are explained in
the
`rattler-build documentation <https://rattler-build.prefix.dev/dev/converting_from_conda_build/>`__.

More details about the v1 recipe format can be found in these five CEPs:

- `CEP-0013 <https://github.com/conda/ceps/blob/main/cep-0013.md>`__
- `CEP-0014 <https://github.com/conda/ceps/blob/main/cep-0014.md>`__
- `CEP-0039 <https://github.com/conda/ceps/blob/main/cep-0039.md>`__
- `CEP-0040 <https://github.com/conda/ceps/blob/main/cep-0040.md>`__
- `CEP-0041 <https://github.com/conda/ceps/blob/main/cep-0041.md>`__
