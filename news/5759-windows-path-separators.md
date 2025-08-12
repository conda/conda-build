### Bug fixes

* Fix path separator handling in test commands with environment variables on Windows. The fix now detects the actual separator used in environment variables and matches path separators accordingly, using efficient string operations to normalize only the specific parts containing environment variables and prevent mixed separator issues that could cause test failures. (#5759 via #5765)
