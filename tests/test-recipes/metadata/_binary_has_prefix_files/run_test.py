import os


def main():
    prefix = os.environ['PREFIX']
    fn = os.path.join(prefix, 'binary-has-prefix')

    with open(fn, 'rb') as f:
        data = f.read()

    print("Prefix: ")
    print(prefix)
    print("Binary data (prefix should be in this): ")
    print(data)
    assert prefix.encode('utf-8') in data

if __name__ == '__main__':
    main()
