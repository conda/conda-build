### Enhancements

* <news item>

### Bug fixes

* Fix `CMAKE_GENERATOR` being overwritten by conda compiler package activation scripts on Windows, which caused builds to fail with CMake 4.0+ due to the removal of the `Win64` platform suffix from Visual Studio generator names. The generator is now set after conda activation and is derived from the actual compiler package being used (e.g., `vs2017` → `Visual Studio 15 2017`). (#5829)

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* <news item>
