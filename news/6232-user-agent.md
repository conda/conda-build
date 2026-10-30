### Enhancements

* Append `conda-build/<version>` to conda's HTTP User-Agent while a conda-build command or public API call is running. The token also covers download threads and is removed when the call returns or raises an exception.
