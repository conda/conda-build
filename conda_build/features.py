from __future__ import absolute_import, division, print_function

import os
import re
import sys

from conda.compat import iteritems


sel_pat = re.compile('FEATURE_(\w+)')

# list of features, where each element is a tuple(name, boolean), i.e.
# having FEATURE_A=1 and FEATURE_B=0 -> [('a', True), ('b', False)]
feature_list = []
for key, value in iteritems(os.environ):
    m = sel_pat.match(key)
    if m:
        if value not in ('0', '1'):
            sys.exit("Error: did not expect environment variable '%s' "
                     "being set to '%s' (not '0' or '1')" % (key, value))
        feature_list.append((m.group(1).lower(), bool(int(value))))
