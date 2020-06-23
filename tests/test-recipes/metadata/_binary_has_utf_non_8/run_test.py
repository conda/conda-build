import os

supported_encodings = [
    'utf-8',
    # Make sure to specify -le and -be so that the UTF endian prefix
    # doesn't show up in the string
    'utf-16-le', 'utf-16-be',
    'utf-32-le', 'utf-32-be'
]


def main():
    for encoding in supported_encodings:
        prefix = os.environ['PREFIX']
        prefix = prefix.encode(encoding)
        fn = os.path.join(
            prefix, 'binary-has-prefix-{encoding}'.format(encoding=encoding)
        with open(fn, 'rb') as f:
            data = f.read()
        print(data)

        assert prefix in data, prefix + b" not found in " + data

if __name__ == '__main__':
    main()
