import os
import sys
import json
import shutil
from os.path import dirname, isdir, join



THIS_DIR = dirname(__file__)

PY_TMPL = """\
if __name__ == '__main__':
    import sys
    from %s import %s

    sys.exit(%s())
"""

prefix = sys.prefix
python = sys.executable


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def create_entry_point(path, module, func):
    pyscript = PY_TMPL % (module, func, func)
    if sys.platform == 'win32':
        with open(path + '-script.py', 'w') as fo:
            fo.write(pyscript)
        shutil.copyfile(join(THIS_DIR,
                             'cli-%d.exe' % (8 * tuple.__itemsize__)),
                        path + '.exe')
    else:
        with open(path, 'w') as fo:
            fo.write('#!%s\n' % python)
            fo.write(pyscript)
        os.chmod(path, int('755', 8))


def create_entry_points(items, remove=False):
    if not items:
        return
    bin_dir = join(prefix, 'Scripts' if sys.platform == 'win32' else 'bin')
    if not isdir(bin_dir):
        os.mkdir(bin_dir)
    for cmd, module, func in items:
        path = join(bin_dir, cmd)
        if remove:
            if sys.platform == 'win32':
                _unlink(path + '-script.py')
                _unlink(path + '.exe')
            else:
                _unlink(path)
        else:
            create_entry_point(path, module, func)


def read_data():
    with open(join(THIS_DIR, 'data.json')) as fi:
        return json.load(fi)


def link():
    d = read_data()
    create_entry_points(d['entry_points'])


def unlink():
    d = read_data()
    create_entry_points(d['entry_points'], remove=True)


def main():
    from optparse import OptionParser
    p = OptionParser()
    p.add_option("--unlink", action="store_true")
    p.add_option("--verbose", action="store_true")
    opts, args = p.parse_args()

    if opts.unlink:
        unlink()
    else:
        link()


if __name__ == '__main__':
    main()
