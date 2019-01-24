****************************
Building Anaconda installers
****************************

Constructor
-----------

* Constructor is the tool we use to generate Anaconda installers. It creates installers
  from conda packages

* Actually, we use a special version of Constructor that allows us to do things like
  inject the VScode plugin

* It takes a constructor.yaml file as a definition as what an installer should look like
  and generates it

  * This notably includes information about channels, what packages should be included,
    and the type of installer (sh, pkg, exe)

  * By default we include the main, free, r, pro, and msys2 (for Windows) channels

Anaconda metapackage
--------------------

* The Anaconda metapackage is what defines exactly what package go into the Anaconda installer

* This will have a pinning down to the version and build hash

* At the time of building the installers, the metapackage will be generated from a conda recipe

* Constructor will put this package into the installer

Build the installer
-------------------

* Take the Anaconda conda recipe and build it to make the Anaconda metapackage

* Generate a constructor.yaml with all the appropriate packages, including the
  Anaconda metapackage, conda-build, etc.

* Use custom constructor to generate the installer

* The process is identical for Anaconda and Miniconda installers
