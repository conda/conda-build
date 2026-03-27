#!/bin/bash
set -ex
if [[ "${target_platform}" == osx-* ]]; then
  mkdir -p "${PREFIX}/lib"
  echo x > "${PREFIX}/lib/libfoo.dylib"
  echo x > "${PREFIX}/lib/libfoo16.16.dylib"
  echo x > "${PREFIX}/lib/libfoo16.dylib"
elif [[ "${target_platform}" == linux-* ]]; then
  mkdir -p "${PREFIX}/lib"
  echo x > "${PREFIX}/lib/libfoo.so"
  echo x > "${PREFIX}/lib/libfoo16.so"
  echo x > "${PREFIX}/lib/libfoo16.so.16"
  echo x > "${PREFIX}/lib/libfoo16.so.16.34.0"
else
  echo "lib-foo: unknown target_platform=${target_platform}" >&2
  exit 1
fi
