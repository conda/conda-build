### Enhancements

* Add ``missing_dso_allowlist`` and ``runpath_allowlist`` as preferred recipe keys. (#5902)

### Bug fixes

* <news item>

### Deprecations

* Deprecate ``build/missing_dso_whitelist`` recipe key in favor of ``build/missing_dso_allowlist``. (#5902)
* Deprecate ``build/runpath_whitelist`` recipe key in favor of ``build/runpath_allowlist``. (#5902)
* Deprecate ``DEFAULT_MAC_WHITELIST`` constant in favor of ``DEFAULT_MAC_ALLOWLIST``. (#5902)
* Deprecate ``DEFAULT_WIN_WHITELIST`` constant in favor of ``DEFAULT_WIN_ALLOWLIST``. (#5902)

### Docs

* Update documentation to use inclusive language (allowlist instead of whitelist). (#5902)

### Other

* Replace internal uses of ``whitelist`` with ``allowlist`` for more inclusive language. (#5902)
