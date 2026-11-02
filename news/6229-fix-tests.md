### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Update tests for `conda-libmamba-solver` 26.10.0, which raises `DependencyNeedsBuildingError` instead of `PackagesNotFoundError` when a recipe dependency is missing from an empty channel. As a result, `conda render` now returns a non-final recipe instead of failing. (#6229)
* Test against a matrix of `conda-libmamba-solver` versions in CI. (#6229)
