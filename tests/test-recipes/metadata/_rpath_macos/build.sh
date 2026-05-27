#!/bin/bash
set -euo pipefail

workdir="${SRC_DIR:-$PWD}/work"
mkdir -p "$workdir" "$PREFIX/lib" "$PREFIX/share/$PKG_NAME"

if [[ "${target_platform:-}" == "osx-arm64" ]]; then
  subdir="osx-arm64"
  pkg="libopenblas-0.3.33-pthreads_hddb8425_0.conda"
  sha256="e1ec1db8ab19f1eddab1d99aba0e30d573e6f33c568fda7cab46390cb0f9bd5a"
else
  subdir="osx-64"
  pkg="libopenblas-0.3.33-pthreads_h705a207_0.conda"
  sha256="3654cdf68d4c9f2d89638310f336a60ecd5121a1"
fi

curl -L --fail \
  -o "$workdir/$pkg" \
  "https://conda.anaconda.org/conda-forge/${subdir}/${pkg}"

echo "${sha256}  $workdir/$pkg" | shasum -a 256 -c -

unzip -o "$workdir/$pkg" -d "$workdir" >/dev/null

tar --use-compress-program=unzstd -xf \
  "$workdir"/pkg-*.tar.zst \
  -C "$workdir"

install "$workdir/lib/libopenblas.0.dylib" \
  "$PREFIX/lib/libopenblas.0.dylib"
