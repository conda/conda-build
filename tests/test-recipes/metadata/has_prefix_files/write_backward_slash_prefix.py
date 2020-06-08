import os

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'backward-slash-prefix')

with open(fn, 'w') as f:
    f.write(prefix.replace('/', '\\'))
