### Enhancements

### Bug fixes

### Deprecations

* Remove optional package checks provided by the unsupported `conda-verify` package.
  The `--verify`, `--no-verify`, and `--strict-verify` options are deprecated no-ops
  and are scheduled for removal in 27.5. The `verify`, `ignore_verify_codes`, and
  `exit_on_verify_error` settings and the recipe's `build/ignore_verify_codes` key
  no longer affect builds. Conda-build's built-in package checks remain in place.

### Docs

### Other

* Remove the `conda-verify` package constraint and benchmark dependency.
