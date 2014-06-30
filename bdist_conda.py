"""
bdist_conda

"""
from __future__ import (print_function, division, unicode_literals,
    absolute_import)

from collections import defaultdict
import configparser

from distutils.command.install import install
from distutils.errors import DistutilsOptionError, DistutilsGetoptError

from conda.compat import StringIO, string_types
from conda.lock import Locked
import conda.config
from conda.cli.common import spec_from_line
from conda_build.metadata import MetaData
from conda_build import config, build, pypi

# TODO: Add support for all the options that conda build has

class bdist_conda(install):
    description = "create a conda package"

    def initialize_options(self):
        super(bdist_conda, self).initialize_options()

    def finalize_options(self):
        opt_dict = self.distribution.get_option_dict('install')
        if self.prefix:
            raise DistutilsOptionError("--prefix is not allowed")
        opt_dict['prefix'] = ("bdist_conda", config.build_prefix)
        super(bdist_conda, self).finalize_options()

    def run(self):
        with Locked(config.croot):
            d = defaultdict(dict)
            # Needs to be lowercase
            d['package']['name'] = self.distribution.metadata.name
            d['package']['version'] = self.distribution.metadata.version
            d['build']['number'] = 0 # TODO: Allow to set this
            # TODO d['build']['entry_points'] = ...
            # MetaData does the auto stuff if the build string is None
            d['build']['string'] = None # Set automatically

            # XXX: I'm not really sure if it is correct to combine requires
            # and install_requires
            d['requirements']['run'] = d['requirements']['build'] = \
                [spec_from_line(i) for i in
                    (self.distribution.metadata.requires or []) +
                    getattr(self.distribution, 'install_requires', [])] + ['python']
            d['about']['home'] = self.distribution.metadata.url
            # Don't worry about classifiers. This isn't skeleton pypi. We
            # don't need to make this work with random stuff in the wild. If
            # someone writes their setup.py wrong and this doesn't work, it's
            # their fault.
            d['about']['license'] = self.distribution.metadata.license
            d['about']['summary'] = self.distribution.description


        # This is similar logic from conda skeleton pypi
        if not hasattr(self.distribution, 'entry_points'):
            return []
        entry_points = self.distribution.entry_points
        if entry_points:
            if isinstance(entry_points, string_types):
                # makes sure it is left-shifted
                newstr = "\n".join(x.strip()
                                   for x in entry_points.split('\n'))
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
                    # Debugging. TODO: Make this optional
                    d['test']['commands'] = pypi.make_entry_tests(entry_list)

            # Debugging for now. We should make this an option.
            d['test']['imports'] = [self.distribution.metadata.name]

            d = dict(d)
            m = MetaData.fromdict(d)
            # Shouldn't fail, but do you really trust the code above?
            m.check_fields()
            build.build(m, post=False)
            # Do the install
            super(bdist_conda, self).run()
            build.build(m, post=True)
            build.test(m)
