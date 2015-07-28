"""
bdist_conda

"""
from __future__ import print_function, division, unicode_literals

from collections import defaultdict
from distutils.command.install import install
from distutils.errors import DistutilsOptionError, DistutilsGetoptError
from distutils.dist import Distribution

from conda.compat import (StringIO, string_types, configparser, PY3, text_type
as unicode)
from conda.lock import Locked
import conda.config
from conda.cli.common import spec_from_line

from conda_build.metadata import MetaData
from conda_build import build, pypi
from conda_build.config import config
from conda_build.cli.main_build import handle_binstar_upload

# TODO: Add support for all the options that conda build has

class CondaDistribution(Distribution):
    """
    Distribution subclass that supports bdist_conda options

    This class is required if you want to pass any bdist_conda specific
    options to setup().  To use, set distclass=CondaDistribution in setup().

    **NOTE**: If you use setuptools, you must import setuptools before
    importing distutils.commands.bdist_conda.

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

    - conda_features: List of features for the package. See the features
      section of the conda build documentation for more information about
      features in conda.

    - conda_track_features: List of features that this package should track
      (enable when installed).  See the features section of the conda build
      documentation for more information about features in conda.

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
        'conda_buildnum': 0,
        'conda_buildstr': None,
        'conda_import_tests': True,
        'conda_command_tests': True,
        'conda_binary_relocation': True,
        'conda_preserve_egg_dir': None,
        'conda_features': None,
        'conda_track_features': None,
        }

    def __init__(self, attrs=None):
        given_attrs = {}
        # We need to remove the attrs so that Distribution.__init__ doesn't
        # warn about them.
        if attrs:
            for attr in self.conda_attrs:
                if attr in attrs:
                    given_attrs[attr] = attrs.pop(attr)

        if not PY3:
            # Distribution is an old-style class in Python 3
            Distribution.__init__(self, attrs)
        else:
            super().__init__(attrs)

        for attr in self.conda_attrs:
            setattr(self.metadata, attr, given_attrs.get(attr, self.conda_attrs[attr]))

class bdist_conda(install):
    description = "create a conda package"

    def initialize_options(self):
        if not PY3:
            # Command is an old-style class in Python 2
            install.initialize_options(self)
        else:
            super().initialize_options()
        self.buildnum = None
        self.binstar_upload = False

    def finalize_options(self):
        opt_dict = self.distribution.get_option_dict('install')
        if self.prefix:
            raise DistutilsOptionError("--prefix is not allowed")
        opt_dict['prefix'] = ("bdist_conda", config.build_prefix)
        if not PY3:
            # Command is an old-style class in Python 2
            install.finalize_options(self)
        else:
            super().finalize_options()

    def run(self):
        # Make sure the metadata has the conda attributes, even if the
        # distclass isn't CondaDistribution. We primarily do this to simplify
        # the code below.

        metadata = self.distribution.metadata

        for attr in CondaDistribution.conda_attrs:
            if not hasattr(metadata, attr):
                setattr(metadata, attr,
                    CondaDistribution.conda_attrs[attr])

        # The command line takes precedence
        if self.buildnum is not None:
            metadata.conda_buildnum = self.buildnum

        with Locked(config.croot):
            d = defaultdict(dict)
            # PyPI allows uppercase letters but conda does not, so we fix the
            # name here.
            d['package']['name'] = metadata.name.lower()
            d['package']['version'] = metadata.version
            d['build']['number'] = metadata.conda_buildnum

            # MetaData does the auto stuff if the build string is None
            d['build']['string'] = metadata.conda_buildstr

            d['build']['binary_relocation'] = metadata.conda_binary_relocation
            d['build']['preserve_egg_dir'] = metadata.conda_preserve_egg_dir
            d['build']['features'] = metadata.conda_features
            d['build']['track_features'] = metadata.conda_track_features

            # XXX: I'm not really sure if it is correct to combine requires
            # and install_requires
            d['requirements']['run'] = d['requirements']['build'] = \
                [spec_from_line(i) for i in
                    (metadata.requires or []) +
                    (getattr(self.distribution, 'install_requires', []) or
                        [])] + ['python']
            if hasattr(self.distribution, 'tests_require'):
                # A lot of packages use extras_require['test'], but
                # tests_require is the one that is officially supported by
                # setuptools.
                d['test']['requires'] = [spec_from_line(i) for i in
                    self.distribution.tests_require or []]

            d['about']['home'] = metadata.url
            # Don't worry about classifiers. This isn't skeleton pypi. We
            # don't need to make this work with random stuff in the wild. If
            # someone writes their setup.py wrong and this doesn't work, it's
            # their fault.
            d['about']['license'] = metadata.license
            d['about']['summary'] = metadata.description

            # This is similar logic from conda skeleton pypi
            entry_points = getattr(self.distribution, 'entry_points', [])
            if entry_points:
                if isinstance(entry_points, string_types):
                    # makes sure it is left-shifted
                    newstr = "\n".join(x.strip() for x in
                        entry_points.split('\n'))
                    c = configparser.ConfigParser()
                    entry_points = {}
                    try:
                        c.readfp(StringIO(newstr))
                    except Exception as err:
                        # This seems to be the best error here
                        raise DistutilsGetoptError("ERROR: entry-points not understood: " + str(err) + "\nThe string was" + newstr)
                    else:
                        for section in config.sections():
                            if section in ['console_scripts', 'gui_scripts']:
                                value = ['%s=%s' % (option, config.get(section, option))
                                         for option in config.options(section)]
                                entry_points[section] = value
                            else:
                                # Make sure setuptools is added as a dependency below
                                entry_points[section] = None

                if not isinstance(entry_points, dict):
                    raise DistutilsGetoptError("ERROR: Could not add entry points. They were:\n" + entry_points)
                else:
                    cs = entry_points.get('console_scripts', [])
                    gs = entry_points.get('gui_scripts', [])
                    # We have *other* kinds of entry-points so we need
                    # setuptools at run-time
                    if not cs and not gs and len(entry_points) > 1:
                        d['requirements']['run'].append('setuptools')
                        d['requirements']['build'].append('setuptools')
                    entry_list = cs + gs
                    if gs and conda.config.platform == 'osx':
                        d['build']['osx_is_app'] = True
                    if len(cs + gs) != 0:
                        d['build']['entry_points'] = entry_list
                        if metadata.conda_command_tests is True:
                            d['test']['commands'] = list(map(unicode, pypi.make_entry_tests(entry_list)))

            if 'setuptools' in d['requirements']['run']:
                d['build']['preserve_egg_dir'] = True

            if metadata.conda_import_tests:
                if metadata.conda_import_tests is True:
                    d['test']['imports'] = ((self.distribution.packages or [])
                                            + (self.distribution.py_modules or []))
                else:
                    d['test']['imports'] = metadata.conda_import_tests

            if (metadata.conda_command_tests and not
                isinstance(metadata.conda_command_tests,
                bool)):
                d['test']['commands'] = list(map(unicode, metadata.conda_command_tests))

            d = dict(d)
            m = MetaData.fromdict(d)
            # Shouldn't fail, but do you really trust the code above?
            m.check_fields()
            build.build(m, post=False)
            # Do the install
            if not PY3:
                # Command is an old-style class in Python 2
                install.run(self)
            else:
                super().run()
            build.build(m, post=True)
            build.test(m)
            if self.binstar_upload:
                class args:
                    binstar_upload = self.binstar_upload
                handle_binstar_upload(build.bldpkg_path(m), args)
            else:
                no_upload_message = """\
# If you want to upload this package to binstar.org later, type:
#
# $ binstar upload %s
""" % build.bldpkg_path(m)
                print(no_upload_message)


# Distutils looks for user_options on the class (not instance).  It also
# requires that it is an instance of list. So we do this here because we want
# to keep the options from the superclass (and because I don't feel like
# making a metaclass just to make this work).

bdist_conda.user_options.extend([
    (str('buildnum='), None, str('''The build number of
    the conda package. Defaults to 0, or the conda_buildnum specified in the
    setup() function. The command line flag overrides the option to
    setup().''')),
    (str('binstar-upload'), None, ("""Upload the finished package to binstar""")),
    ])

bdist_conda.boolean_options.extend([str('binstar-upload')])
