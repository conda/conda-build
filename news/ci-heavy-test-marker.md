### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Introduce a new `@pytest.mark.heavy` marker for long-running integration
  tests (>2 min) that build packages from conda-forge. The five currently
  identified heavy tests (`test_api_build_grpc_issue5645`,
  `test_build_strings_glob_match`, `test_cross_unix_windows_mingw`,
  `test_sysroots_detection`, and `test_conda_py_no_period`) now run in the
  serial CI leg instead of the parallel leg, preventing any single slow
  test from dictating the parallel leg's wall-clock time.
