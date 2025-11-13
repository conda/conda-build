### Enhancements

* <news item>

### Bug fixes

* Fixed BUILD environment variable to respect `cdt_name` variant configuration. Previously, BUILD was hardcoded to use `cos6` or `cos7` based on architecture, ignoring the `cdt_name` variant when specified. Now, if `cdt_name` is provided in the variant configuration, it will be used in the BUILD variable; otherwise, it falls back to the architecture-based default. (#5733)

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* <news item>
