import os
import json
import glob


def main():
    fname = os.path.join(prefix, 'conda-meta',
                         '{env[PKG_NAME]}.json'.format(env=os.environ))
    print('Info from {}'.format(fname))
    prefix = os.environ['PREFIX']
    with open(fname, 'r') as fh:
        info = json.load(fh)

    print('Depends:', info['depends'])
    assert set(info['depends']) == set(["python", "python 3.5.*",
                                        "numpy 1.10.*"])


if __name__ == '__main__':
    main()
