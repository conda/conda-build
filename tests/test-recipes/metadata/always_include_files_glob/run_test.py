import os
import sys
import json


def main():
    prefix = os.environ['PREFIX']
    info_file = os.path.join(prefix, 'conda-meta',
                             'always_include_files_regex-0.1-0.json')
    with open(info_file, 'r') as fh:
        info = json.load(fh)

    if sys.platform == 'darwin':
        assert set(info['files']) == {'lib/libpng.dylib', 'lib/libpng16.16.dylib', 'lib/libpng16.dylib'}
    elif sys.platform.startswith('linux'):
        assert set(info['files']) == {'lib/libpng.so', 'lib/libpng16.so', 'lib/libpng16.so.16', 'lib/libpng16.so.16.17.0'}

if __name__ == '__main__':
    main()
