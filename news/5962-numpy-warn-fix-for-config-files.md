### Bug fixes

* Stop the verbose "No numpy version specified in conda_build_config.yaml" warning when that warning does not apply to config files: parsing of `conda_build_config.yaml` uses a dedicated selector path (`cbc_line_selectors`) that does not look up `numpy` from the (not-yet-merged) variant. The previous behavior on recipe and full metadata rendering is unchanged. (#5962)

### Deprecations

* Remove `conda_build.metadata.ns_cfg`. Use `conda_build.metadata.get_selectors` instead. (#5962)
