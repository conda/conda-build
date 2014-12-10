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

if __name__ == '__main__':
    main()
