.. _configuration:

==================
Configuration
==================

Conda-build can be configured through various methods including environment variables,
command-line arguments, and configuration files. This section documents the available
configuration options and how to use them.

.. _condarc-configuration:

Conda configuration file (.condarc)
==================================

You can configure conda-build behavior by adding settings to your `.condarc` file.
The `.condarc` file can be located in your home directory, the current working
directory, or specified via the `--config-file` command-line option.

Package format configuration
---------------------------

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

Example .condarc file:

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

Package format differences
-------------------------

**Legacy .tar.bz2 format:**
* Traditional conda package format
* Compatible with older conda versions
* Larger file sizes due to less efficient compression
* Slower installation times

**Modern .conda format:**
* Newer, more efficient package format
* Better compression ratios
* Faster installation times
* Requires conda 4.7+ for installation
* Default format in conda-build 25.1+

For detailed information about conda package formats and specifications, see :doc:`package specification <../package-spec>`.

.. _environment-variables:

Environment variables
====================

See :ref:`env-vars` for a complete list of environment variables that can be used
to configure conda-build behavior.

.. _command-line-options:

Command-line options
===================

See the individual command documentation (e.g., :ref:`build_ref`) for available
command-line options that can override configuration file settings.
