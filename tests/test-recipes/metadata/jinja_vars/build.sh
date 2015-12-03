# CONDA_TEST_VAR was inherited via build/script_env
[ "${CONDA_TEST_VAR}" == "conda_test" ]

# CONDA_TEST_VAR_2 was not inherited
[ "${CONDA_TEST_VAR_2}" == "" ]

# Sanity check: Neither was LD_LIBRARY_PATH
[ "$LD_LIBRARY_PATH" == "" ]

# Check the special value we gave the build string, which depends on build number
[ "${PKG_BUILD_STRING}" == "${CONDA_TEST_VAR}_${PKG_BUILDNUM}" ]
