=============
Release notes
=============

This information is drawn from the GitHub conda-build project
changelog: https://github.com/conda/conda-build/blob/master/CHANGELOG.txt

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