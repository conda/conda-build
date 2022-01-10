import os
import json
import glob
import sys


def main():
    prefix = os.environ['PREFIX']

    info_files = glob.glob(os.path.join(prefix, 'conda-meta',
                             'conda-build-test-python-xx-1.0-py35_0.json'))
    assert len(info_files) == 1, "did not find appropriate info file - check build string computation"
    info_file = info_files[0]
    with open(info_file) as fh:
        info = json.load(fh)

    # numpy with no version, python with no version, python with version pin
    depends = sorted(info['depends'])
    assert any(dep.startswith('python ') for dep in depends), depends
    assert sys.version[:3] == ("3.5")


if __name__ == '__main__':
    main()
