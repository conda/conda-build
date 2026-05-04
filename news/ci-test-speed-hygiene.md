### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Speed up CI test runs by removing the blanket `--reruns` on Linux (per-test
  `@pytest.mark.flaky` decorators are still honored), fixing a double-coverage
  misconfiguration (coverage flags now live in the workflow only), reusing a
  single session-scoped conda env for the `testing_env` fixture, switching test
  matrix jobs to a shallow git clone, trimming the disk-cleanup list to just
  the entries that were actually recovering meaningful space, and enabling
  pytest-xdist's `--dist=worksteal` so idle workers pick up tasks from busy
  workers in the parallel test legs.
