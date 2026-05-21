#!/bin/bash
set -euo pipefail

workdir="${SRC_DIR:-$PWD}/work"
mkdir -p "$workdir" "$PREFIX/lib" "$PREFIX/share/$PKG_NAME"

if [[ "${target_platform:-}" == "osx-arm64" ]]; then
  subdir="osx-arm64"
  pkg="libopenblas-0.3.33-pthreads_hddb8425_0.conda"
else
  subdir="osx-64"
  pkg="libopenblas-0.3.33-pthreads_h705a207_0.conda"

curl -L --fail \
  -o "$workdir/$pkg" \
  "https://conda.anaconda.org/conda-forge/${subdir}/${pkg}"

unzip -o "$workdir/$pkg" -d "$workdir" >/dev/null

pkg_archive="$(find "$workdir" -maxdepth 1 -name 'pkg-*.tar.zst' -print -quit)"
test -n "$pkg_archive"

tar --use-compress-program=unzstd \
  -xf "$pkg_archive" \
  -C "$workdir"

install "$workdir/lib/libopenblas.0.dylib" \
  "$PREFIX/lib/libopenblas.0.dylib"
