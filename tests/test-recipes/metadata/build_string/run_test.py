import os
from glob import glob
import json


def main():
    prefix = os.environ['PREFIX']
    info_file = glob(os.path.join(prefix, 'conda-meta', 'conda-build-test-build-string-1.0*.json'))[0]
    with open(info_file, 'r') as fh:
        info = json.load(fh)
    assert info['build_number'] == 0
    assert info['build'].startswith('abc')

if __name__ == '__main__':
    main()
