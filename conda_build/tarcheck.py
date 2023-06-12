# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import tarfile
from os.path import basename, normpath

from conda_build.utils import codec, filter_info_files


def dist_fn(fn):
    if fn.endswith(".tar"):
        return fn[:-4]
    elif fn.endswith(".tar.bz2"):
        return fn[:-8]
    else:
        raise Exception("did not expect filename: %r" % fn)


class TarCheck:
    def __init__(self, path, config):
        self.t = tarfile.open(path)
        self.paths = {m.path for m in self.t.getmembers()}
        self.dist = dist_fn(basename(path))
        self.name, self.version, self.build = self.dist.split("::", 1)[-1].rsplit(
            "-", 2
        )
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, e_type, e_value, traceback):
        self.t.close()

    def info_files(self):
        lista = [
            normpath(p.strip().decode("utf-8"))
            for p in self.t.extractfile("info/files").readlines()
        ]
        seta = set(lista)
        if len(lista) != len(seta):
            raise Exception("info/files: duplicates")

        files_in_tar = [normpath(m.path) for m in self.t.getmembers()]
        files_in_tar = filter_info_files(files_in_tar, "")
        setb = set(files_in_tar)
        if len(files_in_tar) != len(setb):
            raise Exception("info_files: duplicate members")

        if seta == setb:
            return
        for p in sorted(seta | setb):
            if p not in seta:
                print("%r not in info/files" % p)
            if p not in setb:
                print("%r not in tarball" % p)
        raise Exception("info/files")

    def index_json(self):
        info = json.loads(self.t.extractfile("info/index.json").read().decode("utf-8"))
        for varname in "name", "version":
            if info[varname] != getattr(self, varname):
                raise Exception(
                    "{}: {!r} != {!r}".format(
                        varname, info[varname], getattr(self, varname)
                    )
                )
        assert isinstance(info["build_number"], int)

    def prefix_length(self):
        prefix_length = None
        if "info/has_prefix" in self.t.getnames():
            prefix_files = self.t.extractfile("info/has_prefix").readlines()
            for line in prefix_files:
                try:
                    prefix, file_type, _ = line.split()
                # lines not conforming to the split
                except ValueError:
                    continue
                if hasattr(file_type, "decode"):
                    file_type = file_type.decode(codec)
                if file_type == "binary":
                    prefix_length = len(prefix)
                    break
        return prefix_length

    def correct_subdir(self):
        info = json.loads(self.t.extractfile("info/index.json").read().decode("utf-8"))
        assert info["subdir"] in [
            self.config.host_subdir,
            "noarch",
            self.config.target_subdir,
        ], (
            "Inconsistent subdir in package - index.json expecting {},"
            " got {}".format(self.config.host_subdir, info["subdir"])
        )


def check_all(path, config):
    x = TarCheck(path, config)
    x.info_files()
    x.index_json()
    x.correct_subdir()
    x.t.close()


def check_prefix_lengths(files, config):
    lengths = {}
    for f in files:
        length = TarCheck(f, config).prefix_length()
        if length and length < config.prefix_length:
            lengths[f] = length
    return lengths
