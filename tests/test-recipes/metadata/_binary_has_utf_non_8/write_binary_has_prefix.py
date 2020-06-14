import os

supported_encodings = [
    'utf-8',
    # Make sure to specify -le and -be so that the UTF endian prefix
    # doesn't show up in the string
    'utf-16-le', 'utf-16-be',
    'utf-32-le', 'utf-32-be'
]

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'binary-has-prefix')

if not os.path.isdir(prefix):
    os.makedirs(prefix)

with open(fn, 'wb') as f:
    for encoding in supported_encodings:
        f.write(prefix.encode(encoding) + b'\x00\x00\x00\x00')
