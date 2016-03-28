import os
import json


def main():
    prefix = os.environ['PREFIX']
    fname = os.path.join(prefix, 'conda-meta',
                         '{env[PKG_NAME]}.json'.format(env=os.environ))
    print('Info from {}'.format(fname))

    with open(fname, 'r') as fh:
        info = json.load(fh)

    print('Depends:', info['depends'])
    assert set(info['depends']) == set(["python", "python 3.5.*",
                                        "numpy 1.10.*"])


if __name__ == '__main__':
    main()
