#!/bin/sh


function cygpath()
{
  if type -P cygpath.exe > /dev/null 2>&1; then
    echo $(cygpath.exe -u "$@")
  else
    echo $@
  fi
}

env
echo "PREFIX was ${PREFIX}"
PREFIX=$(cygpath -u ${PREFIX})
echo "PREFIX now ${PREFIX}"
exit 0
