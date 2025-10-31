### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Enforced menuinst JSON validation immediately rather than waiting for a future date (#5807)
  * Removed date-based conditional logic - now always raises exceptions for invalid menuinst JSON
  * Simplified validation functions to raise exceptions immediately instead of logging warnings
  * Simplified menuinst validation tests to expect exceptions directly
