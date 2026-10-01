### Deprecations

* Mark `build/missing_dso_whitelist` as deprecated to be removed in 27.3. Use `build/missing_dso_allowlist` instead. (#5902)
* Mark `build/runpath_whitelist` as deprecated to be removed in 27.3. Use `build/runpath_allowlist` instead. (#5902)
* Mark `conda_build.post.check_overlinking_impl(missing_dso_whitelist)` as deprecated to be removed in 27.3. Use `missing_dso_allowlist` instead. (#5902)
* Mark `conda_build.post.check_overlinking_impl(runpath_whitelist)` as deprecated to be removed in 27.3. Use `runpath_allowlist` instead. (#5902)
* Mark `conda_build.post.DEFAULT_MAC_WHITELIST` as deprecated to be removed in 27.3. Use `conda_build.post.DEFAULT_MAC_ALLOWLIST` instead. (#5902)
* Mark `conda_build.post.DEFAULT_WIN_WHITELIST` as deprecated to be removed in 27.3. Use `conda_build.post.DEFAULT_WIN_ALLOWLIST` instead. (#5902)
