### Enhancements

* Add `--exclude-newer` for rendering and building `meta.yaml` recipes with conda
  26.9 or newer and a compatible solver. Apply the cutoff to build, host, and test
  dependencies while keeping the build output channel available for newly built
  packages.
