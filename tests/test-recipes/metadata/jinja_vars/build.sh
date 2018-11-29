# CONDA_TEST_VAR was inherited via build/script_env
[ "${CONDA_TEST_VAR}" == "conda_test" ] || (echo "CONDA_TEST_VAR not passed through, but should have been" && exit 1)

# CONDA_TEST_VAR_2 was not inherited
[ "${CONDA_TEST_VAR_2}" == "" ] || (echo "CONDA_TEST_VAR2 passed through, but should not have been" && exit 1)

# Sanity check: Neither was LD_LIBRARY_PATH
[ "$LD_LIBRARY_PATH" == "" ] || (echo "LD_LIBRARY_PATH passed through, but should not have been" && exit 1)
