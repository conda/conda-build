Enhancements:
-------------

* Add cross-r-base for cross compiling
* Add --build-id-pat option
* macOS: Delete build_prefix rpaths
* Use smarter build_number
* Combine default_structs with FIELDS
* Fix conda render indent from 4 to 2
* macOS: arm64 ci/test-suite setup
* Removing more conda-forge testing deps
* Variants: Be more informative
* more verbosity in tests

Bug fixes:
----------

* Fix symlinks to directories
* Make post-link run_export/library_nature determination less work when CONDA_OFFLINE=1
* Remove Python 2.7 from CI matrix
* Fix test_pypi_installer_metadata (builds against python 3.9 not 3.7)
* tests: Fix test_render_with_python_arg_reduces_subspace
* tests: Update python 3 from 3.5/6 to 3.9 in many
* Set numpy default to 1.16
* tests: Fix pins for numpy_used
* tests: CI: Win: Circumvent delayed expansion
* Install patch or m2-patch, write .sh files as binary, more Win tests
* tests: Avoid issue with coverage==5.0 on Win+Py2.7
* Assume non-revisible patches
* Add flaky marker and --strict-markers to setup.cfg
* Don't sort recipes (Kurt Schelfthout)
* Use extra R_ARGS and fix them
* shell check fix

Deprecations:
-------------

* <news item>

Docs:
-----

* <news item>

Other:
------

* <news item>
