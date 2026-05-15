### Enhancements

* Add ``missing_dso_allowlist`` and ``runpath_allowlist`` as preferred recipe keys. (#5902)

### Bug fixes

* <news item>

### Deprecations

* Deprecate ``build/missing_dso_whitelist`` recipe key in favor of ``build/missing_dso_allowlist`` (pending in 26.9, removal in 27.3). (#5902)
* Deprecate ``build/runpath_whitelist`` recipe key in favor of ``build/runpath_allowlist`` (pending in 26.9, removal in 27.3). (#5902)
* Deprecate ``conda_build.post.check_overlinking_impl``'s ``missing_dso_whitelist`` keyword argument in favor of ``missing_dso_allowlist`` (pending in 26.9, removal in 27.3). (#5902)
* Deprecate ``conda_build.post.check_overlinking_impl``'s ``runpath_whitelist`` keyword argument in favor of ``runpath_allowlist`` (pending in 26.9, removal in 27.3). (#5902)
* Deprecate ``conda_build.post.DEFAULT_MAC_WHITELIST`` constant in favor of ``DEFAULT_MAC_ALLOWLIST`` (pending in 26.9, removal in 27.3). (#5902)
* Deprecate ``conda_build.post.DEFAULT_WIN_WHITELIST`` constant in favor of ``DEFAULT_WIN_ALLOWLIST`` (pending in 26.9, removal in 27.3). (#5902)

### Docs

* Update documentation to use inclusive language (allowlist instead of whitelist). (#5902)

### Other

* Replace internal uses of ``whitelist`` with ``allowlist`` for more inclusive language. (#5902)
