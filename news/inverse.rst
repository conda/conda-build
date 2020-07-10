Enhancements:
-------------

* `list_of_dicts_to_dict_of_lists` and `dict_of_lists_to_list_of_dicts` are now
  iverse to each other, in particular they do not randomize ordering of entries
  anymore. This usually makes no big difference but it makes the build order
  more predictable when building many variants of a package with conda-build.
