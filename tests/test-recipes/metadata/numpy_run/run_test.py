import os
import json
import glob


def main():
    prefix = os.environ['PREFIX']
    info_files = glob.glob(os.path.join(prefix, 'conda-meta',
                             'conda-build-test-numpy-run-1.0-*0.json'))
    assert len(info_files) == 1
    info_file = info_files[0]
    with open(info_file) as fh:
        info = json.load(fh)

    depends = sorted(info['depends'])
    # With no version
    assert depends[-2] == 'numpy'
    assert depends[-1] == 'python'


if __name__ == '__main__':
    main()
