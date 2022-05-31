# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from . import _version
__version__ = _version.get_versions()['version']


# Sub commands added by conda-build to the conda command
sub_commands = [
    'build',
    'convert',
    'develop',
    'index',
    'inspect',
    'metapackage',
    'render'
    'skeleton',
]
