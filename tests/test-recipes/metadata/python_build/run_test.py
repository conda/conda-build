import os
import json


def main():
    prefix = os.environ['PREFIX']
    info_file = os.path.join(prefix, 'conda-meta',
                             'conda-build-test-python-build-1.0-0.json')
    with open(info_file, 'r') as fh:
        info = json.load(fh)

    assert len(info['depends']) == 0

if __name__ == '__main__':
    main()
