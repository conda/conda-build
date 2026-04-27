### Bug fixes

* Fixed `FileNotFoundError: [WinError 206] The filename or extension is too long` by correcting the `chunks()` algorithm used to split long command line calls and consolidating the Windows/non-Windows length limits into a single `MAX_CMD_LINE_LENGTH` constant. (#5122 via #5780)
