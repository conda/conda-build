import os
import re, itertools
from os.path import join
prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'mixed-slash-prefixes')
the_sep = '\\' if '\\' in prefix else '/'
other_sep = '\\' if the_sep == '/' else '\\'
with open(fn, 'w') as f:
    f.write(join(prefix.replace(the_sep, '/'))+'\n')
    f.write(join(prefix.replace(the_sep, '\\'))+'\n')
    bits_prefix = prefix.replace(the_sep, '/').split('/')
    bits_slashed = ['\\' + folder if index % 2 else '/' + folder for index, folder in enumerate(bits_prefix)]
    f.write(''.join(bits_slashed))
