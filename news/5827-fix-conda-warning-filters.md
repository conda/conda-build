### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Fixed conda deprecation warning filters to prevent CI test failures with strict validation. (#5807)
  * Added warning filters for conda.core.prefix_data deprecations (including pip_interop_enabled)
  * Updated conda.trust warning filter to be more specific
  * Updated conda.core.link.PrefixActions warning filter with removal version (26.3)
  * Added warning filter for conda.core.index._supplement_index_with_system deprecated status
  * Added warning filter for conda.base.context.Context.restore_free_channel deprecation
  * Removed obsolete warning filters for conda-index and conda-libmamba-solver
