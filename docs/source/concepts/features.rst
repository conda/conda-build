.. _concepts_features:

========
Features
========

Features are a way to track differences in two packages that have
the same name and version. For example, a feature might indicate
a specialized compiler or runtime, or a fork of a package. The
canonical example of a feature is the MKL feature in Anaconda
Accelerate. Packages that are compiled against MKL, such as
NumPy, have the MKL feature set. The MKL metapackage has the MKL
feature set in ``track_features``, so that installing it installs
the MKL feature. Feature names are independent of package
names---it is a coincidence that MKL is both the name of a
package and the feature that it tracks.

Think of features as belonging to the environment the package is
installed into, not the package itself. When a feature is
installed, conda automatically changes to a package with that
feature if it exists. For example, when the MKL feature is
installed, regular NumPy is removed and the NumPy package with
the MKL feature is installed. Enabling a feature does not
install any packages that are not already installed, but all
future packages with that feature that are installed into that
environment will be preferred.

To install a feature, install a package that tracks it. To remove
a feature, use ``conda remove --features``.

It is a good idea to create a metapackage for ``track_features``.
If you add ``track_features`` to a package that also has versions
without that feature, then the versions without that feature will
never be selected, because conda will always add the feature when
it is installed from the ``track_features`` specification of your
package with the feature.

EXAMPLE: If you want to create some packages with the feature
debug, you would create several packages with the following
code:

.. code-block:: yaml

   build:
     features:
       - debug

Then you would create a special metapackage:

.. code-block:: yaml

   package:
     # This name doesn't have to be the same as the feature, but can avoid confusion if it is
     name: debug
     # This need not relate to the version of any of the packages with the
     # feature. It is just a version for this metapackage.
     version: 1.0

   build:
     track_features:
       - debug

.. or use ``conda install --features``, blocking on
.. https://github.com/conda/conda/issues/543

Activating a feature
--------------------
Note that your package that provides some feature may not be installable if you
do not provide a way to activate that feature (most often, by adding a runtime
or test time dependency on something that has the appropriate ``track_feature``.)

Take for example a recipe that only defines the following for Visual Studio
14:

 .. code-block:: yaml

    build:
     features:
       - vc14

This will not actually be installable unless some runtime or
test time dependency that activates the correct feature is provided:

 .. code-block:: yaml

    build:
     features:
       - vc14
    requirements:
     run:
       - vc 14

For Visual Studio in particular, it is common to use either a
particular Python version (since we adhere to the python.org standards
of which VS version is used to build which Python version) or the vc
package, which `originated at Conda-Forge <https://github.com/conda-forge/staged-recipes/pull/363>`_.
This is different from the vc feature and the vc package is being
pinned to a particular version, while vc9, vc10, and vc14 are actually each
distinct features that are activated by the appropriately versioned
vc package.
