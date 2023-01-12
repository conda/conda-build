==============
Conda channels
==============

Conda-build supports standard `conda channel`_ behavior.


Identical channel and package name problem
==========================================

If the channel and package name are identical, it's possible to encounter a build problem if the short channel name is used.

Let's say your Anaconda.org username or an organization name is ``example``. And suppose you created a package ``example``, whose files' layout is similar to:

.. code-block:: bash

  setup.py
  conda/meta.yaml
  example/

If your build depends on some other packages inside your channel, you will need to add ``-c example``, however, the following code:

.. code-block:: bash

  conda-build ./conda/ -c example

will fail with the following error message (the path will be different):

.. code-block:: bash

  requests.exceptions.HTTPError: 404 Client Error: None for url:
  file:///path/to/your/local/example/noarch/repodata.json
  [...]
  The remote server could not find the noarch directory for the requested channel with
  url: file:///path/to/your/local/example/noarch/repodata.json
  [...]
  As of conda 4.3, a valid channel must contain a `noarch/repodata.json` and
  associated `noarch/repodata.json.bz2` file, even if `noarch/repodata.json`
  is empty. please request that the channel administrator create
  `noarch/repodata.json` and associated `noarch/repodata.json.bz2` files.

This happens because conda-build will consider the directory ``./example/`` in your project
as a channel. This is by design due to conda's CI servers, where the build path can be long,
complicated, and not predictable prior to build.

There are several ways to resolve this issue.

#. Use the URL of the desired channel:

    .. code-block:: bash

      conda-build ./conda/ -c https://conda.anaconda.org/example/

#. Run the build from inside the conda recipe directory:

    .. code-block:: bash

      cd conda
      conda-build . -c example

#. Use the label specification workaround:

  .. code-block:: bash

     conda-build ./conda/ -c example/label/main

  which technically is the same as `-c example`, since main is the default label,
  but now it won't mistakenly find a channel ``example/label/main`` on the local filesystem.

.. _`conda channel`: https://docs.conda.io/projects/conda/en/latest/user-guide/concepts/channels.html
