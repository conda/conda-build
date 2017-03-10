#!/bin/bash

set -e

# Ensure files from non-dependencies are *not* present.
if [[ -f ${PREFIX}/lib/lib2intradependencies.so ]]; then
  echo "ERROR: ${PREFIX}/lib/lib2intradependencies.so not found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi
if [[ -f ${PREFIX}/bin/py2-intradependencies ]]; then
  echo "ERROR: ${PREFIX}/bin/py2-intradependencies found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi
if [[ -f ${PREFIX}/bin/r2-intradependencies ]]; then
  echo "ERROR: ${PREFIX}/bin/r2-intradependencies found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi

if [[ ! -d ${PREFIX}/lib ]]; then
  mkdir -p ${PREFIX}/lib
fi

echo lib1intradependencies.so > ${PREFIX}/lib/lib1intradependencies.so
