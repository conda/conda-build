This is the most simple noarch Python recipe I could think of.
You build the package (as always) using:

    conda build .

Notes:
  * you currently can only build noarch Python on Unix systems
  * this package has a Python module, which can be imported using
    `import foo`
  * this package has a console script `foo` (this will also work on
    Windows when installed)
  * all dependencies of this package are Python version and system
    independent
  * the Python code is written to work on both Python 2 and 3 (noarch
    Python) cannot make use to `2to3` at build time
  * The important bit in the `meta.yaml` file is:

        build:
          noarch_python: True

  * once the noarch conda package is built, it can be uploaded to
    `anaconda.org` using (the normal) `anaconda upload <path>` command,
    and installed, using `conda install -c <user> foo`, just like any
    other conda package
