import os
import sys

prefix = os.environ['PREFIX']
fn = '%s/%s' % (prefix, sys.argv[1])

if not os.path.isdir(prefix):
    os.makedirs(prefix)

with open(fn, 'wb') as f:
    f.write(prefix.encode('utf-8') + b'\x00')
