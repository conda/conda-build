### Enhancements

* Add `test_env_template` config option to speed up environment creation by cloning from a template environment instead of creating from scratch. Uses `conda create --clone` to properly handle prefix replacement in scripts and metadata files. The template is only used when its installed records exactly match the requested name/version/build of every spec, the template contains no extra packages the caller did not ask for, and (when `disable_pip` is set) the template does not contain pip/setuptools/wheel. (#5904)
* Serialize the session-scoped `warm_package_cache` test fixture across pytest-xdist workers via a file lock so only one worker creates the shared template environment, avoiding `LockError`/`InvalidArchiveError` races on `~/conda_pkgs_dir`. (#5904)

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Improved CI test speed by reducing test matrix (skip Python 3.11, reduced matrix for PRs), excluding benchmark tests from regular runs, adding cache restore-keys for better cache hits, reducing flaky test reruns from 3 to 1, switching macOS to faster ARM runners, and adding a session-scoped fixture to pre-warm the package cache and create a template environment for faster test builds. (#5904)
