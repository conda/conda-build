# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This is code that is added to noarch Python packages. See
conda_build/noarch_python.py.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from os.path import dirname, exists, isdir, join, normpath
from pathlib import Path

# Silence pyflakes. This variable is added when link.py is written by
# conda_build.noarch_python.
if False:
    DATA = None

THIS_DIR = dirname(__file__)
PREFIX = normpath(sys.prefix)
if sys.platform == "win32":
    BIN_DIR = join(PREFIX, "Scripts")
    SITE_PACKAGES = "Lib/site-packages"
else:
    BIN_DIR = join(PREFIX, "bin")
    SITE_PACKAGES = "lib/python%s/site-packages" % sys.version[:3]

# the list of these files is going to be store in info/_files
FILES = []

# three capture groups: whole_shebang, executable, options
SHEBANG_REGEX = (
    rb"^(#!"  # pretty much the whole match string
    rb"(?:[ ]*)"  # allow spaces between #! and beginning of the executable path
    rb"(/(?:\\ |[^ \n\r\t])*)"  # the executable is the next text block without an escaped space or non-space whitespace character  # NOQA
    rb"(.*)"  # the rest of the line can contain option flags
    rb")$"
)  # end whole_shebang group


def _link(src, dst):
    try:
        os.link(src, dst)
        # on Windows os.link raises AttributeError
    except (OSError, AttributeError):
        shutil.copy2(src, dst)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def pyc_f(
    path: str | os.PathLike,
    version_info: tuple[int, ...] = sys.version_info,
) -> str:
    path = Path(path)
    if version_info[0] == 2:
        return str(path.with_suffix(".pyc"))
    return str(
        path.parent
        / "__pycache__"
        / f"{path.stem}.cpython-{version_info[0]}{version_info[1]}.pyc"
    )


def link_files(src_root, dst_root, files):
    for f in files:
        src = join(THIS_DIR, src_root, f)
        dst = join(PREFIX, dst_root, f)
        dst_dir = dirname(dst)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        if exists(dst):
            _unlink(dst)
        _link(src, dst)
        f = f"{dst_root}/{f}"
        FILES.append(f)
        if f.endswith(".py"):
            FILES.append(pyc_f(f))


# yanked from conda
def replace_long_shebang(data):
    # this function only changes a shebang line if it exists and is greater than 127 characters
    if hasattr(data, "encode"):
        data = data.encode()
    shebang_match = re.match(SHEBANG_REGEX, data, re.MULTILINE)
    if shebang_match:
        whole_shebang, executable, options = shebang_match.groups()
        if len(whole_shebang) > 127:
            executable_name = executable.decode("utf-8").split("/")[-1]
            new_shebang = "#!/usr/bin/env {}{}".format(
                executable_name, options.decode("utf-8")
            )
            data = data.replace(whole_shebang, new_shebang.encode("utf-8"))
    if hasattr(data, "decode"):
        data = data.decode()
    return data


def create_script(fn):
    src = join(THIS_DIR, "python-scripts", fn)
    dst = join(BIN_DIR, fn)
    if sys.platform == "win32":
        shutil.copy2(src, dst + "-script.py")
        FILES.append("Scripts/%s-script.py" % fn)
        shutil.copy2(
            join(THIS_DIR, "cli-%d.exe" % (8 * tuple.__itemsize__)), dst + ".exe"
        )
        FILES.append("Scripts/%s.exe" % fn)
    else:
        with open(src) as fi:
            data = fi.read()
        with open(dst, "w") as fo:
            shebang = replace_long_shebang("#!%s\n" % normpath(sys.executable))
            fo.write(shebang)
            fo.write(data)
        os.chmod(dst, 0o775)
        FILES.append("bin/%s" % fn)


def create_scripts(files):
    if not files:
        return
    if not isdir(BIN_DIR):
        os.mkdir(BIN_DIR)
    for fn in files:
        create_script(fn)


def main():
    create_scripts(DATA["python-scripts"])
    link_files("site-packages", SITE_PACKAGES, DATA["site-packages"])
    link_files("Examples", "Examples", DATA["Examples"])

    with open(join(PREFIX, "conda-meta", "%s.files" % DATA["dist"]), "w") as fo:
        for f in FILES:
            fo.write("%s\n" % f)


if __name__ == "__main__":
    main()
