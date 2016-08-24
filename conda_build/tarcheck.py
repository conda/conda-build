from __future__ import absolute_import, division, print_function

import json
from os.path import basename
import tarfile

from conda_build.utils import codec


def dist_fn(fn):
    if fn.endswith('.tar'):
        return fn[:-4]
    elif fn.endswith('.tar.bz2'):
        return fn[:-8]
    else:
        raise Exception('did not expect filename: %r' % fn)


class TarCheck(object):
    def __init__(self, path):
        self.t = tarfile.open(path)
        self.paths = set(m.path for m in self.t.getmembers())
        self.dist = dist_fn(basename(path))
        self.name, self.version, self.build = self.dist.split('::', 1)[-1].rsplit('-', 2)

    def info_files(self):
        if 'py_' in self.build:
            return
        lista = [p.strip().decode('utf-8') for p in
                 self.t.extractfile('info/files').readlines()]
        seta = set(lista)
        if len(lista) != len(seta):
            raise Exception('info/files: duplicates')

        listb = [m.path for m in self.t.getmembers()
                 if not (m.path.startswith('info/') or m.isdir())]
        setb = set(listb)
        if len(listb) != len(setb):
            raise Exception('info_files: duplicate members')

        if seta == setb:
            return
        for p in sorted(seta | setb):
            if p not in seta:
                print('%r not in info/files' % p)
            if p not in setb:
                print('%r not in tarball' % p)
        raise Exception('info/files')

    def index_json(self):
        info = json.loads(self.t.extractfile('info/index.json').read().decode('utf-8'))
        for varname in 'name', 'version', 'build':
            if info[varname] != getattr(self, varname):
                raise Exception('%s: %r != %r' % (varname, info[varname],
                                                  getattr(self, varname)))
        assert isinstance(info['build_number'], int)

    def prefix_length(self):
        prefix_length = None
        if 'info/has_prefix' in self.t.getnames():
            prefix_files = self.t.extractfile('info/has_prefix').readlines()
            for line in prefix_files:
                try:
                    prefix, file_type, containing_file = line.split()
                # lines not conforming to the split
                except ValueError:
                    continue
                if hasattr(file_type, 'decode'):
                    file_type = file_type.decode(codec)
                if file_type == 'binary':
                    prefix_length = len(prefix)
                    break
        return prefix_length


def check_all(path):
    x = TarCheck(path)
    x.info_files()
    x.index_json()
    x.t.close()


def check_prefix_lengths(files, min_prefix_length=255):
    lengths = {}
    for f in files:
        length = TarCheck(f).prefix_length()
        if length and length < min_prefix_length:
            lengths[f] = length
    return lengths
