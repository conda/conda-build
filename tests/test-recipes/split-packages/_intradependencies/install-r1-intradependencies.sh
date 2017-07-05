#!/bin/bash

set -e

# Ensure files from dependencies are present during the install of dependents.
if [[ ! -f ${PREFIX}/lib/lib1intradependencies.so ]]; then
  echo "ERROR: ${PREFIX}/lib/lib1intradependencies.so not found during install of ${PKG_NAME} and it is a dependency"
  exit 1
fi

# Ensure files from non-dependencies are *not* present.
if [[ -f ${PREFIX}/lib/lib2intradependencies.so ]]; then
  echo "ERROR: ${PREFIX}/lib/lib2intradependencies.so found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi
if [[ -f ${PREFIX}/bin/py2-intradependencies ]]; then
  echo "ERROR: ${PREFIX}/bin/py2-intradependencies found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi
if [[ -f ${PREFIX}/bin/py1-intradependencies ]]; then
  echo "ERROR: ${PREFIX}/bin/py1-intradependencies found during install of ${PKG_NAME} and it is not a dependency"
  exit 1
fi

if [[ ! -d ${PREFIX}/bin ]]; then
  mkdir -p ${PREFIX}/bin
fi

${R} --slave --no-restore -e cat\(\'r1-intradependencies\'\) > ${PREFIX}/bin/r1-intradependencies
