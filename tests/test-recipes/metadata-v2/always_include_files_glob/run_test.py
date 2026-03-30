import os
import sys
import json
from glob import glob


def main():
    prefix = os.environ['PREFIX']
    info_file = glob(os.path.join(prefix, 'conda-meta',
                             'conda-build-test-always_include_files-glob-1.0-*.json'))[0]
    with open(info_file) as fh:
        info = json.load(fh)

    if sys.platform == 'darwin':
        assert set(info['files']) == {'lib/libfoo.dylib',
                                      'lib/libfoo16.16.dylib',
                                      'lib/libfoo16.dylib',
                                      'top_level.txt'}, info['files']
    elif sys.platform.startswith('linux'):
        assert set(info['files']) == {'lib/libfoo.so',
                                      'lib/libfoo16.so',
                                      'lib/libfoo16.so.16',
                                      'lib/libfoo16.so.16.34.0',
                                      'top_level.txt'}, info['files']
    elif sys.platform == 'win32':
        assert set(info['files']) == {'Library/lib/libfoo.lib',
                                      'Library/lib/libfoo16.lib',
                                      'Library/lib/libfoo16_static.lib',
                                      'Library/lib/libfoo_static.lib',
                                      'top_level.txt'}

if __name__ == '__main__':
    main()
