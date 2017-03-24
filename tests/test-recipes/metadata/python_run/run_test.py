import os
import json
import glob


def main():
    prefix = os.environ['PREFIX']
    info_files = glob.glob(os.path.join(prefix, 'conda-meta',
                             'conda-build-test-python-run-1.0-*0.json'))
    assert len(info_files) == 1
    info_file = info_files[0]
    with open(info_file, 'r') as fh:
        info = json.load(fh)

    assert len(info['depends']) == 1
    assert info['depends'][0] == 'python', info['depends']


if __name__ == '__main__':
    main()
