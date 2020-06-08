import os
import re, itertools
from os.path import join

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'mixed-slash-prefix')
the_sep = '\\' if '\\' in prefix else '/'
other_sep = '\\' if the_sep == '/' else '\\'

with open(fn, 'w') as f:
    f.write(join(prefix.replace(the_sep, '/'))+'\n')
    f.write(join(prefix.replace(the_sep, '\\'))+'\n')
    f.write(re.sub('(/)', lambda m, c=itertools.count(): m.group() if next(c) % 2 else other_sep, prefix))
