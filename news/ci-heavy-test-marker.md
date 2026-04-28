### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Introduce an `@pytest.mark.heavy` marker for five high-duration integration
  tests. They now run in the CI matrix leg named `serial`, while both test legs
  continue to use pytest-xdist, to distribute the workload more evenly.
