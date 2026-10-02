### Bug fixes

* Don't retry definitive solver unsatisfiability or missing-package errors in
  `get_package_records` and `create_env`; unsatisfiable recipes now fail after a
  single solver attempt instead of `1 + max_env_retry` attempts. Lock-related
  errors in `create_env` are also re-raised once retries are exhausted instead
  of being silently swallowed. (#6151)
