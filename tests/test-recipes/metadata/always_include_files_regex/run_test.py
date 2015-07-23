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
        assert sorted(info['files']) == [u'lib/libpng.dylib', u'lib/libpng16.16.dylib', u'lib/libpng16.dylib']
    elif sys.platform == 'linux2':
        assert sorted(info['files']) == ['lib/libpng.so', 'lib/libpng16.so', 'lib/libpng16.so.16', 'lib/libpng16.so.16.17.0']
    elif sys.platform == 'win32':
        assert sorted(info['files']) == [r'Library\lib\libpng.lib', r'Library\lib\libpng16.lib', r'Library\lib\libpng16_static.lib', r'libpng_static.lib']

if __name__ == '__main__':
    main()
