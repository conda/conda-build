### Enhancements

* Add `--exclude-newer` for recipe dependencies with conda 26.9 or newer. Support
  `meta.yaml` with a compatible conda solver and `recipe.yaml` with py-rattler-build
  bindings that support cutoff policies. Apply the cutoff to build, host, and test
  dependencies while keeping the build output channel available for newly built
  packages.
