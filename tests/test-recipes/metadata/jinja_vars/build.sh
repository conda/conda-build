# CONDA_TEST_VAR was inherited via build/script_env
[ "${CONDA_TEST_VAR}" == "conda_test" ]

# CONDA_TEST_VAR_2 was not inherited
[ "${CONDA_TEST_VAR_2}" == "" ]

# Sanity check: Neither was LD_LIBRARY_PATH
[ "$LD_LIBRARY_PATH" == "" ]
