import sys
import os
from os.path import join


def main():
    prefix = os.environ['PREFIX']

    with open(join(prefix, 'automatic-prefix')) as f:
        data = f.read()

    print('automatic-prefix')
    print(data)
    assert prefix in data

    with open(join(prefix, 'has-prefix')) as f:
        data = f.read()

    print('has-prefix')
    print(data)
    assert prefix in data

    with open(join(prefix, 'binary-has-prefix'), 'rb') as f:
        data = f.read()

    print('binary-has-prefix')
    print(data)
    assert prefix.encode('utf-8') in data

    if sys.platform == 'win32':
        forward_slash_prefix = prefix.replace('\\', '/')
        with open(join(prefix, 'forward-slash-prefix')) as f:
            data = f.read()

        print('forward-slash-prefix')
        print(data)
        assert forward_slash_prefix in data

if __name__ == '__main__':
    main()
