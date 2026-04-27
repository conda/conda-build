### Bug fixes

* Stop the verbose "No numpy version specified in conda_build_config.yaml" warning when that warning does not apply to config files: parsing of `conda_build_config.yaml` now uses a dedicated selector path (`cbc_line_selectors`) that does not look up `numpy` from the (not-yet-merged) variant. The previous behavior on recipe and full metadata rendering is unchanged. (PR #5962)
