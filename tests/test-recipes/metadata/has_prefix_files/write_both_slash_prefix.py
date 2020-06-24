import os

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'both-slash-prefix')

with open(fn, 'w') as f:
    f.write('\n'.join((prefix.replace('/', '\\'), prefix.replace('\\', '/'))))
