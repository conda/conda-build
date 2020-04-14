#!/usr/bin/env bash

# On Unix 'bin/test_entry_points_have_prefix' is a python script so it is expected that we will
#   replace the prefix and things will just work (heck, even if it were binary, we'd replace it)
$CONDA_PREFIX/bin/test_entry_points_have_prefix_CASED | rg "entry_point called ok"
if [[ $? != 0 ]]; then
  echo "$CONDA_PREFIX/bin/test_entry_points_have_prefix_CASED did not emit \"entry_point called ok\""
  exit 1
fi
# .. so on Unix we do not expect the (text) file to contain '_h_env'
rg --with-filename -v "_h_env" $CONDA_PREFIX/bin/test_entry_points_have_prefix_CASED
if [[ $? != 0 ]]; then
  echo "$CONDA_PREFIX/bin/test_entry_points_have_prefix_CASED contains \"_h_env\""
  echo ".. it should have been replaced"
  exit 1
fi
rg --with-filename -v "_h_env" $CONDA_PREFIX/somewhere/explicitly-listed-text-file-containing-prefix
if [[ $? != 0 ]]; then
  echo "$CONDA_PREFIX/somewhere/explicitly-listed-text-file-containing-prefix contains \"_h_env\""
  echo ".. it should have been replaced"
  exit 1
fi
rg --with-filename    "_h_env" $CONDA_PREFIX/somewhere/explicitly-not-listed-text-file-containing-prefix
if [[ $? != 0 ]]; then
  echo "$CONDA_PREFIX/somewhere/explicitly-not-listed-text-file-containing-prefix does not contain \"_h_env\""
  echo ".. it should *not* have been replaced"
  exit 1
fi
