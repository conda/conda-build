*********************
Installing with conda
*********************

Conda install
-------------

* When you `conda install <package>` the happy path (with no dependencies)

  * conda looks at your configured channels (in priority)

  * reaches out to the repodata associated with your channels/platform

  * parses repodata to search for the package

  * once the package is found, pulls it down and installs

Specifying channels
-------------------

* From the command line use `--channel`

.. code-block:: bash

  $ conda install scipy --channel conda-forge

* From the command line use `--override-channels` to only search the specified channel

.. code-block:: bash

  $ conda search scipy --channel file:/<path to>/local-channel --override-channels

* In .condarc with the keys

  * channels: list of channels for conda to search for packages

  * default_channels: normally pointing to channels at repo.continuum.io, sets the
    list of "default channels"

  * allow_other_channels: a boolean value that determines if the user may install
    packages outside of the channels list

  * channel_alias: sets an alias for a channel. For example, if `channel_alias: https://my.repo`
    then

    .. code-block:: bash

      conda install --channel me <package>

    is equivalent to

    .. code-block:: bash

      conda install --channel https://my.repo/me <package>
