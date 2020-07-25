Enhancements:
-------------

* allow manual specification of which binary files to prefix replace (#3952)
* many fixes for DSO post-processing (#3952, #3953)
* add support for (limited) tbd parsing (#3953)
* re-wrote apply_patch() to be more robust (#3952)
* filter out '.AppleDouble' folders from recipe searches (#3952)
* convert info.d/*.yaml to info/*.json (#3952)
* move old host env instead of deleting it when `--keep-old-work` (#3952)
* make life easier (less shell exit-y) for those who source test scripts (#3952)
* which_package can be passed avoid_canonical_channel_name (#3952)

Bug fixes:
----------

* conda_build.metadata: fixed typos in FIELDS (#3866)
* add spaces in CRAN templates (#3944)
* raise valid CalledProcessException in macho.otool (#3952)
* cache local_output_folder too for get_build_index (#3952)

Deprecations:
-------------

* <news item>

Docs:
-----

* update cli help information for conda index (#3931)

Other:
------

* drop duplicate get_summary call

