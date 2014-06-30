"""
bdist_conda

"""
from __future__ import (print_function, division, unicode_literals,
    absolute_import)

from collections import defaultdict

from distutils.command.install import install
from distutils.errors import DistutilsOptionError

from conda.lock import Locked
from conda_build.metadata import MetaData
from conda_build import config, build

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

            # TODO: Probably needs to be parsed
            d['requirements']['run'] = d['requirements']['build'] = \
                (self.distribution.metadata.requires or []) + ['python']
            d['about']['home'] = self.distribution.metadata.url
            # Don't worry about classifiers. This isn't skeleton pypi. We
            # don't need to make this work with random stuff in the wild. If
            # someone writes their setup.py wrong and this doesn't work, it's
            # their fault.
            d['about']['license'] = self.distribution.metadata.license
            d['about']['summary'] = self.distribution.description

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
