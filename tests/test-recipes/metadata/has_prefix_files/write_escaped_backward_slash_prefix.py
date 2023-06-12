import os

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'escaped-backward-slash-prefix')

with open(fn, 'w') as f:
    f.write(prefix.replace('\\', '\\\\').replace("/", "\\\\"))
