### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Add a fast, synthetic regression test for the transitive `pin_subpackage`/variant-merge
  bug (#5645, #5644) that runs in seconds instead of the ~15-18 minutes required by the
  real grpc/pytorch recipes, and remove the original tests. A second synthetic recipe
  and test render the same regression under a `conda_build_config.yaml` that forces
  "cross-compilation" (`build_platform != target_platform`), since the original #5644
  reproduction (pytorch_cpu) only triggered the bug while actually cross-compiling.
  (#5645, #5644 via #6054)
