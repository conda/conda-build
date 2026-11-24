.. _configuration:

=============
Configuration
=============

Conda-build can be configured through various methods, including environment variables,
command-line arguments, and configuration files. This section documents the available
configuration options and how to use them.

.. _conda cli configuration: https://docs.conda.io/projects/conda/en/latest/user-guide/configuration/use-condarc.html

The priority of configuration options is as follows (as per the `conda cli documentation`_):
1. Command-line arguments
2. Environment variables
3. Conda configuration file (`.condarc`)
4. Default values (if any)

.. _command-line-options:

Command-line options
===================

See the individual command documentation (e.g., :ref:`build_ref`) for available
command-line options that can override configuration file settings.

.. _environment-variables:

Environment variables
====================

See :ref:`env-vars` for a complete list of environment variables that can be used
to configure conda-build behavior.


.. _condarc-configuration:

Conda configuration file (.condarc)
==================================

You can configure conda-build behavior by adding settings to your `.condarc` file.
The `.condarc` file can be located in your home directory, the current working
directory, or specified via the `--config-file` command-line option. conda-build
has its own section in the `.condarc` file, which is used to configure conda-build.
Also, note that other conda configurations may also affect conda-build behavior,
such as the `channels` setting.

Package format configuration example
------------------------------------

The package format determines which type of conda package is created during the build
process. Conda-build supports two package formats:

* **Legacy format (.tar.bz2)**: The traditional conda package format
* **Modern format (.conda)**: The newer, more efficient package format (default)

You can configure the default package format using the `conda_build.pkg_format` setting
in your `.condarc` file:

.. code-block:: yaml

   conda_build:
     pkg_format: 2  # Use .conda format (default)
     # or
     pkg_format: 1  # Use .tar.bz2 format

Accepted values for `pkg_format`:

* `1` or `"1"` - Legacy .tar.bz2 format
* `2` or `"2"` - Modern .conda format (default)
* `.tar.bz2` - Legacy format (alternative syntax)
* `.conda` - Modern format (alternative syntax)

.. _condarc-example:

Example `.condarc` file
=======================

.. code-block:: yaml

   conda_build:
     pkg_format: 1
     verbose: true
     debug: false

   channels:
     - conda-forge
     - defaults

.. note::

   The package format can also be specified per-build using the `--package-format`
   command-line option, which will override the condarc setting.
