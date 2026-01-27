### Enhancements

* Add `test_env_template` config option to speed up environment creation by cloning from a template environment instead of creating from scratch. Uses platform-specific fast copy methods: APFS copy-on-write on macOS, reflinks on Linux (btrfs/xfs), and `shutil.copytree` elsewhere. (#5904)

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Improved CI test speed by reducing test matrix (skip Python 3.11, reduced matrix for PRs), excluding benchmark tests from regular runs, adding cache restore-keys for better cache hits, reducing flaky test reruns from 3 to 1, switching macOS to faster ARM runners, and adding a session-scoped fixture to pre-warm the package cache and create a template environment for faster test builds. (#5904)
