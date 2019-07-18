=============
Release notes
=============

This information is drawn from the GitHub conda-build project
changelog: https://github.com/conda/conda-build/blob/master/CHANGELOG.txt

3.18.8 (2019-07-18)
-------------------

Enhancements
^^^^^^^^^^^^

* License_file can optionally be a yaml list


Bug fixes
^^^^^^^^^

* Fix readup of existing index.json in cache while extracting
* Fix spurious post build errors/warning message
* Merge channeldata from all urls


Contributors
^^^^^^^^^^^^

* @msarahan
* @rrigdon
* @jjhelmus
* @isuruf
* @ddamiani


3.18.7 (2019-07-09)
-------------------

Enhancements
^^^^^^^^^^^^

* Update authorship for 3.18.7
* Add note on single threading for indexing during build
* Add in fallback for run_exports when channeldata not available
* Make pins for current_repodata additive - always newest, and pins are additions to that
* Limit indexing in build to using one thread
* Speed up by allowing empty run_exports entries in channeldata be valid results
* Bump conda-package-handling to 1.3+
* Add test for run_exports without channeldata
* Fallback to file-based run_exports if channeldata has no results
* Add Mozilla as valid license family
* Add in fallback for run_exports when channeldata not available
* Updated tutorials and resource documentation


Bug fixes
^^^^^^^^^
* Flake8 and test fixes from pytest deprecations
* Fix in render.py::_read_specs_from_package
* Fix for pkg_loc
* Fix conda debug output being suppressed


Contributors
^^^^^^^^^^^^

* @msarahan
* @rrigdon
* @scopatz
* @mbargull
* @jakirkham
* @oleksandr-pavlyk



3.18.6 (2019-06-26)
-------------------

Enhancements
^^^^^^^^^^^^

* Package sha256 sums are included in index.html

Bug fixes
^^^^^^^^^

* Fix bug where package filenames were not included in the index.html

Contributors
^^^^^^^^^^^^

* @rrigdon
* @jjhelmus


3.18.5 (2019-06-25)
-------------------

Bug fixes
^^^^^^^^^

* Fix one more keyerror with missing timestamp data
* When indexing, allow .tar.bz2 files to use .conda cache, but not vice versa.  This acts as a sanity check on the .conda files.
* Add build/rpaths_patcher to meta.yaml to allow switching between lief and patchelf for binary mangling

Contributors
^^^^^^^^^^^^

* @mingwandroid
* @msarahan
* @csosborn


3.18.4 (2019-06-21)
-------------------

Enhancements
^^^^^^^^^^^^

* Channeldata reworked a bit to try to capture any available run_exports for all versions available

Bug fixes
^^^^^^^^^

* Make "timestamp" an optional field in conda index operations

Contributors
^^^^^^^^^^^^

* @msarahan


3.18.3 (2019-06-20)
-------------------

Enhancements
^^^^^^^^^^^^

* Make VS2017 default Visual Studio
* Add hook for customizing the behavior of conda render
* Drop `/usr` from CDT skeleton path
* Update cran skeleton to use m2w64 compilers for windows instead of toolchain.
  The linter is telling since long: Using toolchain directly in this manner is deprecated.

Bug fixes
^^^^^^^^^

* Update cran skeleton to not use toolchain for win
* Fix package_has_file so it supports .conda files (use cph)
* Fix package_has_file function for .conda format
* Fix off-by-one path trimming in prefix_files
* Disable overlinking checks when no files in the package have any shared library linkage
* Try to avoid finalizing top-level metadata twice
* Try to address permission errors on Appveyor and Azure by falling back to copy and warning (not erroring) if removing a file after copying fails
* Reduce the files inspected/loaded for channeldata, so that indexing goes faster

Deprecations
^^^^^^^^^^^^

* The repodata2.json file is no longer created as part of indexing.  It was not used by anything.  It has been removed as an optimization.  Its purpose was to explore namespaces and we'll bring its functionality back when we address that fully.

Contributors
^^^^^^^^^^^^

* @mingwandroid
* @msarahan
* @rrigdon
* @soapy1
* @mariusvniekerk
* @jakirkham
* @dbast
* @duncanmmacleod


3.18.2 (2019-05-26)
-------------------

Bug fixes
^^^^^^^^^

* Speed up post-link checks
* Fix activation not running during tests
* Improve indexing to show status better, and fix bug where size/hashes were being mixed up between .tar.bz2 and .conda files


Contributors
^^^^^^^^^^^^

* @mingwandroid
* @msarahan
* @rrigdon


3.18.1 (2019-05-18)
-------------------

Enhancements
^^^^^^^^^^^^

* Rearrange steps in index.py to optimize away unnecessary work
* Restore parallel extract and hash in index operations

Contributors
^^^^^^^^^^^^

* @msarahan


3.18.0 (2019-05-17)
-------------------

Enhancements
^^^^^^^^^^^^

* Set R_USER environment variable when building R packages
* Make Centos 7 default cdt distribution for linux-aarch64
* Bump default Python3 version to 3.7 for CI
* Build docs if any docs related file changes
* Add support for conda pkgv2 (.conda) format
* Add creation of "current_repodata.json" - like repodata.json, but only has the newest version of each file
* Change repodata layout to support .conda files. They live under the "packages.conda" key and have similar subkeys to their .tar.bz2 counterparts.
* Always show display actions, regardless of verbosity level
* Ignore registry autorun for all cmd.exe invocations
* Relax default pinning on r-base for benefit of noarch R packages
* Make conda index produce repodata_from_packages.json{,.bz2} which contains unpatched metadata
* Use a shorter environment prefix when testing on unix-like platforms
* Prevent pip from clobbering conda installed Python packages by populating .dist_info INSTALLER file


Bug fixes
^^^^^^^^^

* Allow build/missing_dso_whitelist section to be empty
* Make conda-debug honor custom channels passed using -c
* Do not attempt linkages inspection via lief if not installed
* Fix all lief related regressions brought in v3.17.x
* Fix ZeroDivisionError in ELF sections that have zero entries
* `binary_has_prefix_files` and `text_has_prefix_files` now override the automatically detected prefix replacement mode
* Handle special characters properly in pypi conda skeleton
* Build recipes in order of dependencies when passed to CB as directories
* Fix run_test script name for recipes with multiple outputs
* Fix recursion error with subpackages and build_id
* Avoid mutating global variable to fix tests on Windows
* Update CRAN license test case (replace r-ruchardet with r-udpipe)
* Update utils.filter_files to filter out generated .conda_trash files
* Replace stdlib glob with utils.glob. Latter supports recursion (**)


Docs
^^^^

* Updated Sphinx theme to make notes and warnings more visible
* Added tutorial on building R-language packages using skeleton CRAN
* Add 37 to the list of valid values for CONDA_PY
* Corrected argparse rendering error
* Added tutorials section, reorganized content, and added a Windows tutorial
* Added Concepts section, removed extraneous content
* Added release notes section
* Reorganized sections
* Clarify to use 'where' on Windows and 'which' on Linux to inspect files in PATH
* Add RPATH information to compiler-tools documentation
* Improve the documentation on how to use the macOS SDK in build scripts.
* Document ``conda build purge-all``.
* Fix user-guide index
* Add example for meta.yaml
* Updated theme
* Reorganized conda-build topics, updated link-scripts

Contributors
^^^^^^^^^^^^

* @mingwandroid
* @msarahan
* @rrigdon
* @jjhelmus
* @nehaljwani
* @scopatz
* @Bezier89
* @rrigdon
* @isuruf
* @teake
* @jdblischak
* @bilderbuchi
* @soapy1
* @ESSS
* @tjd2002
* @tovrstra
* @chrisburr
* @katietz
* @hrzafer
* @zdog234
* @gabrielcnr
* @saraedum
* @uilianries
* @theultimate1
* @scw
* @spalmrot-tic

3.17.8 (2019-01-26)
-------------------

Bug fixes
^^^^^^^^^

* Provide fallback from libarchive back to Python tarfile handling for handling tarfiles containing symlinks on windows

Other
^^^^^

* Rever support added for releasing conda-build

Contributors
^^^^^^^^^^^^

* @msarahan
* @jjhelmus
* @scopatz
* @rrigdon
* @ax3l
* @rrigdon


3.17.7 (2019-01-16)
-------------------

Bug fixes
^^^^^^^^^

* Respect context.offline setting  #3328
* Don't write bytecode when building noarch: Python packages  #3330
* Escape path separator in repl  #3336
* Remove deprecated sudo statement from travis CI configuration  #3338
* Fix running of test scripts in outputs  #3343
* Allow overriding one key of zip_keys as long as length of group agrees  #3344
* Fix compatibility with conda 4.6.0+  #3346
* Update centos 7 skeleton (CDT) URL  #3350

Contributors
^^^^^^^^^^^^

* @iainsgillis
* @isuruf
* @jjhelmus
* @nsoranzo
* @msarahan
* @qwhelan