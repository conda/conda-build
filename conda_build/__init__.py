# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

import logging

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions


# Sub commands added by conda-build to the conda command
sub_commands = [
    'build',
    'convert',
    'develop',
    'index',
    'inspect',
    'metapackage',
    'pipbuild',
    'render'
    'sign',
    'skeleton',
]


# unclutter logs - show messages only once
class DuplicateFilter(object):
    def __init__(self):
        self.msgs = set()

    def filter(self, record):
        rv = record.msg not in self.msgs
        self.msgs.add(record.msg)
        return rv

dedupe_handler = logging.StreamHandler()
filt = DuplicateFilter()
dedupe_handler.addFilter(filt)
logging.getLogger(__name__).addHandler(dedupe_handler)
