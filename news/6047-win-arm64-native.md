### Enhancements

* <news item>

### Bug fixes

* Make CMD subprocesses match `build_platform` architecture when running emulated Python processes. (#6048 via #6047)
* `recipe.yaml` build/host platform handling now behaves in the same as it did in `meta.yaml`. Accidentally allowed `{build,host}_platform` settings in `conda_build_config.yaml` are no longer valid; instead, users can export `CONDA_SUBDIR` and define the `target_platform` setting, respectively. (#6047)

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* <news item>
