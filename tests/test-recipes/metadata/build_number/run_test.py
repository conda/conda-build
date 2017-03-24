import os
from glob import glob
import json


def main():
    prefix = os.environ['PREFIX']
    info_file = glob(os.path.join(prefix, 'conda-meta', 'conda-build-test-build-number-1.0*.json'))[0]
    with open(info_file, 'r') as fh:
        info = json.load(fh)
    assert info['build_number'] == 1

if __name__ == '__main__':
    main()
