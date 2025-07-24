import os
import json
from pathlib import Path
import sys


def main():
    info_files = list(Path(os.environ['PREFIX'], 'conda-meta').glob('conda-build-test-python-build-run-1.0-py*0.json'))
    assert len(info_files) == 1

    info = json.loads(info_files[0].read_text())
    if sys.version_info < (3, 13):
        assert len(info['depends']) == 1

        # python with version pin
        python, = info['depends']
        assert python.startswith('python ')
    else:
        assert len(info['depends']) == 2

        # python and python_abi with version pin
        assert any(dep.startswith('python ') for dep in info['depends'])
        assert any(dep.startswith('python_abi ') for dep in info['depends'])


if __name__ == '__main__':
    main()
