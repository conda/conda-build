import os
import sys
import json


def main():
    prefix = os.environ['PREFIX']
    info_file = os.path.join(prefix, 'conda-meta',
                             'conda-build-test-always_include_files-glob-1.0-0.json')
    with open(info_file, 'r') as fh:
        info = json.load(fh)

    if sys.platform == 'darwin':
        assert set(info['files']) == {'lib/libpng.dylib',
                                      'lib/libpng16.16.dylib',
                                      'lib/libpng16.dylib'}, info['files']
    elif sys.platform.startswith('linux'):
        assert set(info['files']) == {'lib/libpng.so',
                                      'lib/libpng16.so',
                                      'lib/libpng16.so.16',
                                      'lib/libpng16.so.16.17.0'}, info['files']
    elif sys.platform == 'win32':
        assert sorted(info['files']) == ['Library/lib/libpng.lib',
                                         'Library/lib/libpng16.lib',
                                         'Library/lib/libpng16_static.lib',
                                         'Library/lib/libpng_static.lib']

if __name__ == '__main__':
    main()
