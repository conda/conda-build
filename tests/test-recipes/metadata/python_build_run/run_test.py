import os
import json
from pathlib import Path


def main():
    info_files = list(Path(os.environ['PREFIX'], 'conda-meta').glob('conda-build-test-python-build-run-1.0-py*0.json'))
    assert len(info_files) == 1

    info = json.loads(info_files[0].read_text())
    assert len(info['depends']) == 1

    # python with version pin
    python, = info['depends']
    assert python.startswith('python ')


if __name__ == '__main__':
    main()
