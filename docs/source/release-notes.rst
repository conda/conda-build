=============
Release notes
=============

This information is drawn from the GitHub conda-build project
changelog: https://github.com/conda/conda-build/blob/master/CHANGELOG.txt

3.17.8 (2019-01-26)
-------------------

Bug fixes
^^^^^^^^^^

* provide fallback from libarchive back to python tarfile handling for handling tarfiles containing symlinks on windows

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

* respect context.offline setting  #3328
* don't write bytecode when building noarch: python packages  #3330
* escape path separator in repl  #3336
* remove deprecated sudo statement from travis CI configuration  #3338
* fix running of test scripts in outputs  #3343
* allow overriding one key of zip_keys as long as length of group agrees  #3344
* fix compatibility with conda 4.6.0+  #3346
* update centos 7 skeleton (CDT) URL  #3350

Contributors
^^^^^^^^^^^^

* @iainsgillis
* @isuruf
* @jjhelmus
* @nsoranzo
* @msarahan
* @qwhelan