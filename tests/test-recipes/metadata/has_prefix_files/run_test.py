import sys
import os
from os.path import join


def main():
    prefix = os.environ['PREFIX'].replace("\\", "/")

    with open(join(prefix, 'unlisted-text-prefix')) as f:
        data = f.read()

    print('unlisted-text-prefix')
    print(data)
    assert prefix not in data, prefix + " not found in unlisted-text-prefix" + data

    with open(join(prefix, 'has-prefix')) as f:
        data = f.read()

    print('has-prefix')
    print(data)
    assert prefix in data, prefix + " not found in has-prefix" + data

    if sys.platform == 'win32':
        forward_slash_prefix = prefix.replace('\\', '/')
        with open(join(prefix, 'forward-slash-prefix')) as f:
            data = f.read()

        print('forward-slash-prefix')
        print(data)
        assert forward_slash_prefix in data, prefix + " not found in " + data
    else:
        with open(join(prefix, 'binary-has-prefix'), 'rb') as f:
            data = f.read()
        print('binary-has-prefix')
        print(data)
        assert prefix.encode('utf-8') in data, prefix + " not found in binary-has-prefix" + data

if __name__ == '__main__':
    main()
