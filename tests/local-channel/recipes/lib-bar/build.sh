#!/bin/bash
set -ex
if [[ "${target_platform}" == osx-* ]]; then
  mkdir -p "${PREFIX}/lib"
  echo x > "${PREFIX}/lib/libbar.9.dylib"
  echo x > "${PREFIX}/lib/libbar.dylib"
elif [[ "${target_platform}" == linux-* ]]; then
  mkdir -p "${PREFIX}/lib"
  echo x > "${PREFIX}/lib/libbar.so.9"
  echo x > "${PREFIX}/lib/libbar.so"
else
  echo "lib-bar: unknown target_platform=${target_platform}" >&2
  exit 1
fi
