import os

supported_encodings = [
    'utf-8',
    # Make sure to specify -le and -be so that the UTF endian prefix
    # doesn't show up in the string
    'utf-16-le', 'utf-16-be',
    'utf-32-le', 'utf-32-be'
]

prefix = os.environ['PREFIX']

if not os.path.isdir(prefix):
    os.makedirs(prefix)

for encoding in supported_encodings:
    fn = os.path.join(
        prefix, 'binary-has-prefix-{encoding}'.format(encoding=encoding))
    with open(fn, 'wb') as f:
        f.write(prefix.encode(encoding) + b'\x00\x00\x00\x00')
