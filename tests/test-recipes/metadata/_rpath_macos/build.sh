#!/bin/bash
set -euo pipefail

workdir="${SRC_DIR:-$PWD}/work"

mkdir -p "$workdir" "$PREFIX/lib" "$PREFIX/share/$PKG_NAME"

if [[ "${target_platform:-}" == "osx-arm64" ]]; then
  pkg="libopenblas-0.3.33-pthreads_hddb8425_0.conda"
else
  pkg="libopenblas-0.3.33-pthreads_h705a207_0.conda"
fi


unzip -o "$pkg" -d "$workdir" >/dev/null

tar --use-compress-program=unzstd -xf \
  "$workdir"/pkg-*.tar.zst \
  -C "$workdir"

install "$workdir/lib/libopenblas.0.dylib" \
  "$PREFIX/lib/libopenblas.0.dylib"
