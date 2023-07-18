# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
bdist_conda

"""

import sys
import time
from collections import defaultdict

from setuptools.command.install import install
from setuptools.dist import Distribution
from setuptools.errors import BaseError, OptionError

from conda_build import api
from conda_build.build import handle_anaconda_upload
from conda_build.conda_interface import StringIO, configparser, spec_from_line
from conda_build.config import Config
from conda_build.metadata import MetaData
from conda_build.skeletons import pypi

# TODO: Add support for all the options that conda build has


class GetoptError(BaseError):
    """The option table provided to 'fancy_getopt()' is bogus."""


class CondaDistribution(Distribution):
    """
    Distribution subclass that supports bdist_conda options

    This class is required if you want to pass any bdist_conda specific
    options to setup().  To use, set distclass=CondaDistribution in setup().

    Options that can be passed to setup() (must include
    distclass=CondaDistribution):

    - conda_buildnum: The build number. Defaults to 0. Can be overridden on
      the command line with the --buildnum flag.

    - conda_buildstr: The build string. Default is generated automatically
      from the Python version, NumPy version if relevant, and the build
      number, like py34_0.

    - conda_import_tests: Whether to automatically run import tests. The
      default is True, which runs import tests for the all the modules in
      "packages". Also allowed are False, which runs no tests, or a list of
      module names to be tested on import.

    - conda_command_tests: Command line tests to run. Default is True, which
      runs ``command --help`` for each ``command`` in the console_scripts and
      gui_scripts entry_points. Also allowed are False, which doesn't run any
      command tests, or a list of command tests to run.

    - conda_binary_relocation: Whether binary files should be made relocatable
      (using install_name_tool on OS X or patchelf on Linux). The default is
      True. See the "making packages relocatable" section in the conda build
      documentation for more information on this.

    - conda_preserve_egg_dir: Whether to preserve the egg directory as
      installed by setuptools.  The default is True if the package depends on
      setuptools or has a setuptools entry_points other than console_scripts
      and gui_scripts.

    Command line options:

    --buildnum: Set the build number. Defaults to the conda_buildnum passed to
      setup(), or 0. Overrides any conda_buildnum passed to setup().

    """

    # Unfortunately, there's no way to warn the users that they need to use
    # distclass=CondaDistribution when they try to use a conda option to
    # setup(). Distribution.__init__ will just print a warning when it sees an
    # attr it doesn't recognize, and then it is discarded.

    # attr: default
    conda_attrs = {
        "conda_buildnum": 0,
        "conda_buildstr": None,
        "conda_import_tests": True,
        "conda_command_tests": True,
        "conda_binary_relocation": True,
        "conda_preserve_egg_dir": None,
        "conda_features": None,
        "conda_track_features": None,
    }

    def __init__(self, attrs=None):
        given_attrs = {}
        # We need to remove the attrs so that Distribution.__init__ doesn't
        # warn about them.
        if attrs:
            for attr in self.conda_attrs:
                if attr in attrs:
                    given_attrs[attr] = attrs.pop(attr)

        super().__init__(attrs)

        for attr in self.conda_attrs:
            setattr(self.metadata, attr, given_attrs.get(attr, self.conda_attrs[attr]))


class bdist_conda(install):
    description = "create a conda package"
    config = Config(
        build_id="bdist_conda" + "_" + str(int(time.time() * 1000)), build_is_host=True
    )

    def initialize_options(self):
        super().initialize_options()
        self.buildnum = None
        self.anaconda_upload = False

    def finalize_options(self):
        opt_dict = self.distribution.get_option_dict("install")
        if self.prefix:
            raise OptionError("--prefix is not allowed")
        opt_dict["prefix"] = ("bdist_conda", self.config.host_prefix)
        super().finalize_options()

    def run(self):
        # Make sure the metadata has the conda attributes, even if the
        # distclass isn't CondaDistribution. We primarily do this to simplify
        # the code below.

        metadata = self.distribution.metadata

        for attr in CondaDistribution.conda_attrs:
            if not hasattr(metadata, attr):
                setattr(metadata, attr, CondaDistribution.conda_attrs[attr])

        # The command line takes precedence
        if self.buildnum is not None:
            metadata.conda_buildnum = self.buildnum

        d = defaultdict(dict)
        # PyPI allows uppercase letters but conda does not, so we fix the
        # name here.
        d["package"]["name"] = metadata.name.lower()
        d["package"]["version"] = metadata.version
        d["build"]["number"] = metadata.conda_buildnum

        # MetaData does the auto stuff if the build string is None
        d["build"]["string"] = metadata.conda_buildstr

        d["build"]["binary_relocation"] = metadata.conda_binary_relocation
        d["build"]["preserve_egg_dir"] = metadata.conda_preserve_egg_dir
        d["build"]["features"] = metadata.conda_features
        d["build"]["track_features"] = metadata.conda_track_features

        # XXX: I'm not really sure if it is correct to combine requires
        # and install_requires
        d["requirements"]["run"] = d["requirements"]["build"] = [
            spec_from_line(i)
            for i in (metadata.requires or [])
            + (getattr(self.distribution, "install_requires", []) or [])
        ] + ["python"]
        if hasattr(self.distribution, "tests_require"):
            # A lot of packages use extras_require['test'], but
            # tests_require is the one that is officially supported by
            # setuptools.
            d["test"]["requires"] = [
                spec_from_line(i) for i in self.distribution.tests_require or []
            ]

        d["about"]["home"] = metadata.url
        # Don't worry about classifiers. This isn't skeleton pypi. We
        # don't need to make this work with random stuff in the wild. If
        # someone writes their setup.py wrong and this doesn't work, it's
        # their fault.
        d["about"]["license"] = metadata.license
        d["about"]["summary"] = metadata.description

        # This is similar logic from conda skeleton pypi
        entry_points = getattr(self.distribution, "entry_points", [])
        if entry_points:
            if isinstance(entry_points, str):
                # makes sure it is left-shifted
                newstr = "\n".join(x.strip() for x in entry_points.splitlines())
                c = configparser.ConfigParser()
                entry_points = {}
                try:
                    c.read_file(StringIO(newstr))
                except Exception as err:
                    # This seems to be the best error here
                    raise GetoptError(
                        "ERROR: entry-points not understood: "
                        + str(err)
                        + "\nThe string was"
                        + newstr
                    )
                else:
                    for section in c.sections():
                        if section in ["console_scripts", "gui_scripts"]:
                            value = [
                                f"{option}={c.get(section, option)}"
                                for option in c.options(section)
                            ]
                            entry_points[section] = value
                        else:
                            # Make sure setuptools is added as a dependency below
                            entry_points[section] = None

            if not isinstance(entry_points, dict):
                raise GetoptError(
                    "ERROR: Could not add entry points. They were:\n" + entry_points
                )
            else:
                rs = entry_points.get("scripts", [])
                cs = entry_points.get("console_scripts", [])
                gs = entry_points.get("gui_scripts", [])
                # We have *other* kinds of entry-points so we need
                # setuptools at run-time
                if not rs and not cs and not gs and len(entry_points) > 1:
                    d["requirements"]["run"].append("setuptools")
                    d["requirements"]["build"].append("setuptools")
                entry_list = rs + cs + gs
                if gs and self.config.platform == "osx":
                    d["build"]["osx_is_app"] = True
                if len(cs + gs) != 0:
                    d["build"]["entry_points"] = entry_list
                    if metadata.conda_command_tests is True:
                        d["test"]["commands"] = list(
                            map(str, pypi.make_entry_tests(entry_list))
                        )

        if "setuptools" in d["requirements"]["run"]:
            d["build"]["preserve_egg_dir"] = True

        if metadata.conda_import_tests:
            if metadata.conda_import_tests is True:
                d["test"]["imports"] = (self.distribution.packages or []) + (
                    self.distribution.py_modules or []
                )
            else:
                d["test"]["imports"] = metadata.conda_import_tests

        if metadata.conda_command_tests and not isinstance(
            metadata.conda_command_tests, bool
        ):
            d["test"]["commands"] = list(map(str, metadata.conda_command_tests))

        d = dict(d)
        self.config.keep_old_work = True
        m = MetaData.fromdict(d, config=self.config)
        # Shouldn't fail, but do you really trust the code above?
        m.check_fields()
        m.config.set_build_id = False
        m.config.variant["python"] = ".".join(
            (str(sys.version_info.major), str(sys.version_info.minor))
        )
        api.build(m, build_only=True, notest=True)
        self.config = m.config
        # prevent changes in the build ID from here, so that we're working in the same prefix
        # Do the install
        super().run()
        output = api.build(m, post=True, notest=True)[0]
        api.test(output, config=m.config)
        m.config.clean()
        if self.anaconda_upload:

            class args:
                anaconda_upload = self.anaconda_upload

            handle_anaconda_upload(output, args)
        else:
            no_upload_message = (
                """\
# If you want to upload this package to anaconda.org later, type:
#
# $ anaconda upload %s
"""
                % output
            )
            print(no_upload_message)


# Distutils looks for user_options on the class (not instance).  It also
# requires that it is an instance of list. So we do this here because we want
# to keep the options from the superclass (and because I don't feel like
# making a metaclass just to make this work).

bdist_conda.user_options.extend(
    [
        (
            "buildnum=",
            None,
            """The build number of
    the conda package. Defaults to 0, or the conda_buildnum specified in the
    setup() function. The command line flag overrides the option to
    setup().""",
        ),
        ("anaconda-upload", None, ("""Upload the finished package to anaconda.org""")),
    ]
)

bdist_conda.boolean_options.extend(["anaconda-upload"])
