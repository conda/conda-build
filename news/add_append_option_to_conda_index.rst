Enhancements:
-------------

* Adds `--append` to `conda-index` which allows a user to append to a `repodata.json`. This is useful because sometimes a user may not have the entire channel locally to run `conda-index` against. As an example, if a user wanted to upload a single package to a channel, this would allow them to simply download the `repodata.json` run `conda-index --append $PATH_TO_REPODATA $PATH_TO_PKGS` and have an up-to-date `repodata.json`.

Bug fixes:
----------

* <news item>

Deprecations:
-------------

* <news item>

Docs:
-----

* <news item>

Other:
------

* <news item>
