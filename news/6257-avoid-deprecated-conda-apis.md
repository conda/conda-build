### Other

* Don't use `NoPackagesFoundError` or `conda.resolve`, which conda 26.10 marks for deprecation. Use `conda.exceptions.ResolvePackageNotFound` instead, and query repodata through `SubdirData` for `conda skeleton cpan` version lookups. (#6257)
