import os
import sys
from glob import glob
import json


def main():
    prefix = os.environ['PREFIX']
    info_file = glob(os.path.join(prefix, 'conda-meta', 'conda-build-test-python-build-1.0*.json'))[0]
    with open(info_file) as fh:
        info = json.load(fh)

    if sys.version_info[0:2] < (3, 13):
        assert len(info['depends']) == 0, info['depends']
    else:
        # there is a strong export from python starting with py313
        assert len(info['depends']) == 1, info['depends']
        assert any(dep.startswith("python_abi ") for dep in info['depends'])

if __name__ == '__main__':
    main()
