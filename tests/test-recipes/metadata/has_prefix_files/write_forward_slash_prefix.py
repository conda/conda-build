import os

prefix = os.environ['PREFIX']
fn = os.path.join('%s' % prefix, 'forward-slash-prefix')

with open(fn, 'w') as f:
    f.write(prefix)
    f.write(prefix.replace('\\', '/'))
