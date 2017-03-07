#!/bin/bash

set -e

# Ensure files from non-dependencies are *not* present.
if [[ -f ${PREFIX}/lib/lib1intradependencies.so ]]; then
  echo "ERROR: ${PREFIX}/lib/lib1intradependencies.so not found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi
if [[ -f ${PREFIX}/bin/py1-intradependencies ]]; then
  echo "ERROR: ${PREFIX}/bin/py1-intradependencies found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi
if [[ -f ${PREFIX}/bin/r1-intradependencies ]]; then
  echo "ERROR: ${PREFIX}/bin/r1-intradependencies found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi

if [[ ! -d ${PREFIX}/lib ]]; then
  mkdir -p ${PREFIX}/lib
fi

echo lib2intradependencies.so > ${PREFIX}/lib/lib2intradependencies.so
