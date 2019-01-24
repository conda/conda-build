********************
Anatomy of a package
********************

What is a “conda package”?
--------------------------

* A compressed tarball file that may contain

  * python or other modules

  * executables

  * etc.

* Package format is the same across platforms

* Conda understands how to install these packages into a conda environment
  so that it may be available when that environment is active

Using packages
---------------

* You may search for packages

.. code-block:: bash

  conda search scipy


* You may install a package

.. code-block:: bash

  conda install scipy


* You may build a package

.. code-block:: bash

  conda build my_fun_package

Package structure
-----------------

.. code-block:: bash

  .
  ├── bin
  │   └── pyflakes
  ├── info
  │   ├── LICENSE.txt
  │   ├── files
  │   ├── index.json
  │   ├── paths.json
  │   └── recipe
  └── lib
      └── python3.5

* bin contains relevant binaries for the package

* lib contains the relevant library files (eg. the .py files)

* info contains package metadata

Info
----

* files

  * a list of all the files in the package (not included in info/)

* index.json

  * metadata about the package including platform, version, dependencies, build info
  
.. code-block:: bash

  {
    "arch": "x86_64",
    "build": "py37hfa4b5c9_1",
    "build_number": 1,
    "depends": [
      "depend > 1.1.1"
    ],
    "license": "BSD 3-Clause",
    "name": "fun-packge",
    "platform": "linux",
    "subdir": "linux-64",
    "timestamp": 1535416612069,
    "version": "0.0.0"
  }

* paths.json

  * a list of files in the package, along with their associated SHA-256, size in bytes,
    and the type of path (eg. hardlink vs. softlink)

.. code-block:: bash

  {
    "paths": [
      {
        "_path": "lib/python3.7/site-packages/fun-packge/__init__.py",
        "path_type": "hardlink",
        "sha256": "76f3b6e34feeb651aff33ca59e0279c4eadce5a50c6ad93b961c846f7ba717e9",
        "size_in_bytes": 2067
      },
      {
        "_path": "lib/python3.7/site-packages/fun-packge/__config__.py",
        "path_type": "hardlink",
        "sha256": "348e3602616c1fe4c84502b1d8cf97c740d886002c78edab176759610d287f06",
        "size_in_bytes": 87519
      },
      ...
  }
