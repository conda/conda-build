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
        super(bdist_conda, self).finalize_options()
        if self.prefix:
            raise DistutilsOptionError("--prefix is not allowed")
        self.prefix = config.build_prefix

    def run(self):
        with Locked(config.croot):
            super(bdist_conda, self).run()
            d = defaultdict(dict)
            # Insert metadata here
            d['package']['name'] = self.distribution.metadata.name
            d['package']['version'] = self.distribution.metadata.version
            d['build']['number'] = 0 # TODO: Allow to set this
            # TODO d['build']['entry_points'] = ...
            # MetaData does the auto stuff if the build string is None
            d['build']['string'] = None # Set automatically

            # TODO: Probably needs to be parsed
            d['requirements']['run'] = self.distribution.metadata.requires
            d['about']['home'] = self.distribution.metadata.url

            # TODO: Use similar code from skeleton pypi to get this from the
            # classifiers
            d['about']['license'] = self.distribution.metadata.license
            d['about']['summary'] = self.distribution.description

            d = dict(d)
            m = MetaData.fromdict(d)
            # Shouldn't fail, but do you really trust the code above?
            m.check_fields()
            build.build(m)
            build.test(m)
