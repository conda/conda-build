import os

prefix = os.environ['PREFIX']
fn = '%s/forward-slash-prefix' % prefix

with open(fn, 'w') as f:
    f.write(prefix.replace('\\', '/'))
