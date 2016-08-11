from __future__ import absolute_import, division, print_function

import os
import sys

from .conda_interface import iteritems


env_vars = [
    'FEATURE_DEBUG',
    'FEATURE_NOMKL',
    'FEATURE_OPT',
]

# list of features, where each element is a tuple(name, boolean), i.e. having
# FEATURE_DEBUG=1 and FEATURE_NOMKL=0 -> [('debug', True), ('nomkl', False)]
feature_list = []
for key, value in iteritems(os.environ):
    if key in env_vars:
        if value not in ('0', '1'):
            sys.exit("Error: did not expect environment variable '%s' "
                     "being set to '%s' (not '0' or '1')" % (key, value))
        feature_list.append((key[8:].lower(), bool(int(value))))
