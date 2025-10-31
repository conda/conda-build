### Enhancements

* <news item>

### Bug fixes

* Fixed logic error in Windows MSVC version detection for Python 3.5+ (#5807)
* Updated CMake generator handling for CMake 4 compatibility (#5807)

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Updated CMakeLists.txt to use CMake 3.5 minimum requirement (more modern standard) (#5807)
  * Changed from CMake 2.6 to 3.5 to be compatible with CMake 4
  * CMake 2 was last released in Dec 2013, CMake 4 was just built on main (Oct 17 2025)
* Updated Windows CMake generator to not use platform suffixes for CMake 4 compatibility (#5807)
  * CMake 4.1.2+ no longer supports platform suffixes in Visual Studio generator names
  * New approach is compatible with CMake 3.1+ (2014+)
* Added Python 3.6 compiler variant support (vs2022) for Windows (#5807)
* Fixed bld.bat CMake generator variable reference (#5807)
