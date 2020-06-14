import os


def main():
    prefix = os.environ['PREFIX']
    fn = os.path.join(prefix, 'binary-has-prefix')
    prefix = prefix.encode('utf-8')

    with open(fn, 'rb') as f:
        data = f.read()

    print(data)
    assert prefix in data, prefix + b" not found in " + data

if __name__ == '__main__':
    main()
