********************************
Channels and generating an index
********************************

Channel layout
--------------

.. code-block:: bash

  .
  ├── channeldata.json
  ├── linux-32
  |   ├── repodata.json
  │   └── package-0.0.0.tar.bz2
  ├── linux-64
  |   ├── repodata.json
  │   └── package-0.0.0.tar.bz2
  ├── win-64
  |   ├── repodata.json
  │   └── package-0.0.0.tar.bz2
  ├── win-32
  |   ├── repodata.json
  │   └── package-0.0.0.tar.bz2
  ├── osx-64
  |   ├── repodata.json
  │   └── package-0.0.0.tar.bz2
  ...

Parts of a channel
------------------

* Channeldata.json contains metadata about the channel, including:

    - What subdirs the channel contains.
    - What packages exist in the channel and what subdirs they are in.

* Subdirs are associated with platforms. For example, the linux-64 subdir contains
  packages for linux-64 systems.

* Repodata.json contains an index of the packages in a subdir. Each subdir will
  have it's own repodata.

* Channels have packages as tarballs under corresponding subdirs.

channeldata.json
----------------

.. code-block:: bash

  {
    "channeldata_version": 1,
    "packages": {
      "super-fun-package": {
        "activate.d": false,
        "binary_prefix": false,
        "deactivate.d": false,
        "home": "https://github.com/Home/super-fun-package",
        "license": "BSD",
        "post_link": false,
        "pre_link": false,
        "pre_unlink": false,
        "reference_package": "win-64/super-fun-package-0.1.0-py37_0.tar.bz2",
        "run_exports": {},
        "subdirs": [
          "win-64"
        ],
        "summary": "A fun package! Open me up for rainbows",
        "text_prefix": false,
        "version": "0.1.0"
      },
      "subdirs": [
        "win-64",
        ...
      ]
  }

repodata.json
-------------

.. code-block:: bash

  {
    "packages": {
      "super-fun-package-0.1.0-py37_0.tar.bz2": {
        "build": "py37_0",
        "build_number": 0,
        "depends": [
          "some-depends"
        ],
        "license": "BSD",
        "md5": "a75683f8d9f5b58c19a8ec5d0b7f796e",
        "name": "super-fun-package",
        "sha256": "1fe3c3f4250e51886838e8e0287e39029d601b9f493ea05c37a2630a9fe5810f",
        "size": 3832,
        "subdir": "win-64",
        "timestamp": 1530731681870,
        "version": "0.1.0"
      },
      ...
    }

How an index is generated
-------------------------

For each subdir:

* Look at all the packages that exist in the subdir.

* Generate a list of packages to add/update/remove.

* Remove all packages that need to be removed.

For all packages that need to be added/updated:

  * Extract the package to access metadata including full package name,
    mtime, size, and index.json.

  * Add package to repodata.

Example: Building a channel
---------------------------

To build a local channel and put a package in it, follow the directions below.

#. Make the channel structure.

    .. code-block:: bash

      $ mkdir local-channel
      $ cd local-channel
      $ mkdir linux-64 osx-64

#. Put your favorite package in the channel.

    .. code-block:: bash

      $ wget https://anaconda.org/anaconda/scipy/1.1.0/download/linux-64/scipy-1.1.0-py37hfa4b5c9_1.tar.bz2 -P linux-64
      $ wget https://anaconda.org/anaconda/scipy/1.1.0/download/osx-64/scipy-1.1.0-py37hf5b7bf4_0.tar.bz2 -P osx-64

#. Run a conda index. This will generate both channeldata.json for the channel and
   repodata.json for the linux-64 and osx-64 subdirs, along with some other files.

    .. code-block:: bash

      $ conda index .

#. Check your work by searching the channel.

    .. code-block:: bash

      $ conda search -c file:/<path to>/local-channel scipy | grep local-channel
