### Bug fixes

* Fix path separator handling in pytest commands with --ignore flag and SP_DIR on Windows. This resolves issues where mixed forward and backward slashes in paths could cause pytest to fail. (#5759)
