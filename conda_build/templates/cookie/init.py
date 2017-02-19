from __future__ import absolute_import, division, print_function

from ._version import get_versions
versions = get_versions()
__version__ = version['version']
__git_revision__ = version['full-revisionid']
del get_versions, versions
