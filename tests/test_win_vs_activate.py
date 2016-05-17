from __future__ import print_function

import os
import subprocess
import sys

import pytest
import mock


vcvars_backup_files = {}
if sys.platform == "win32":
    from conda_build.windows import (build_vcvarsall_vs_path,
                                     VCVARS64_VS9_BAT_PATH,
                                     WIN_SDK_71_BAT_PATH)

    vcvars_backup_files = {"vs{}".format(version): [build_vcvarsall_vs_path(version)]
                           for version in ["9.0", "10.0", "14.0"]}
    vcvars_backup_files['vs9.0'].append(VCVARS64_VS9_BAT_PATH)
    vcvars_backup_files['vs10.0'].append(WIN_SDK_71_BAT_PATH)

    vs9 = {key: vcvars_backup_files[key] for key in ['vs9.0']}
    vs10 = {key: vcvars_backup_files[key] for key in ['vs10.0']}
    vs14 = {key: vcvars_backup_files[key] for key in ['vs14.0']}

    vcs = {"9.0": vs9, "10.0": vs10, "14.0": vs14}


def write_bat_files(good_locations):
    for label, locations in vcvars_backup_files.items():
        for location in locations:
            # these should all have been moved!  bad to overwrite them!
            assert not os.path.exists(location)
            if not os.path.isdir(os.path.dirname(location)):
                # if any of these are made, they are not currently cleaned up.  Sorry.
                os.makedirs(os.path.dirname(location))
            with open(location, "w") as f:
                print("writing {} (exit /b {})".format(location, int(label not in good_locations)))
                f.write("::  NOTE: exit code of 1 here means incorrect VS version activated.  "
                        "check logic.\n")
                f.write("exit /b {}\n".format(int(label not in good_locations)))


@pytest.fixture(scope="function")
def setup_teardown(request):
    def fin():
        for locations in vcvars_backup_files.values():
            for location in locations:
                # clean up any of the custom scripts we wrote to test
                if os.path.exists(location):
                    os.remove(location)
                # restore the backups
                if os.path.exists(location[:-1] + 'k'):
                    os.rename(location[:-1] + 'k', location)
    request.addfinalizer(fin)

    # backup known files
    for locations in vcvars_backup_files.values():
        for location in locations:
            if os.path.exists(location):
                os.rename(location, location[:-1] + 'k')

    return request


@pytest.fixture(scope="function", params=vcvars_backup_files.keys())
def compiler(request, setup_teardown):
    return request.param


@pytest.fixture(params=[32, 64])
def bits(request):
    return request.param


@pytest.fixture(params=['9.0', '10.0', '14.0'])
def default_vs(request):
    return request.param


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only test")
@pytest.mark.xfail(reason="verification of test logic", strict=True)
def test_activation_logic(bits, compiler):
    from conda_build.windows import msvc_env_cmd
    # empty list here means no configuration is valid.  We should get a
    # failure.
    write_bat_files([])
    # look up which VS version we're forcing here
    compiler_version = [key for key in vcs if compiler in vcs[key]][0]
    with open('tmp_call.bat', "w") as f:
        f.write(msvc_env_cmd(bits, override=compiler_version))
    subprocess.check_call(['cmd.exe', '/C', 'tmp_call.bat'], shell=True)


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only test")
def test_activation(bits, compiler):
    write_bat_files([compiler])
    from conda_build.windows import msvc_env_cmd, VS_VERSION_STRING
    # look up which VS version we're forcing here
    compiler_version = [key for key in vcs if compiler in vcs[key]][0]
    # this will throw an exception if the subprocess return code is not 0
    #     this is effectively the test condition for all below tests.
    with open('tmp_call.bat', "w") as f:
        f.write(msvc_env_cmd(bits, override=compiler_version))
        f.write('\nif not "%VS_VERSION%" == "{}" exit /b 1'.format(compiler_version))
        f.write('\nif not "%VS_MAJOR%" == "{}" exit /b 1'.format(compiler_version.split('.')[0]))
        f.write('\nif not "%VS_YEAR%" == "{}" exit /b 1'
                .format(VS_VERSION_STRING[compiler_version][-4:]))
        f.write('\nif not "%CMAKE_GENERATOR%" == "{}" exit /b 1'
                .format(VS_VERSION_STRING[compiler_version] +
                        {64: ' Win64', 32: ''}[bits]))
    try:
        subprocess.check_call(['cmd.exe', '/C', 'tmp_call.bat'], shell=True)
    except subprocess.CalledProcessError:
        print("failed activation: {}, {}".format(bits, compiler))
        raise
    finally:
        os.remove('tmp_call.bat')


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only test")
def test_no_override(bits, default_vs):
    with mock.patch('conda_build.windows.config') as mock_config:
        from conda_build.windows import msvc_env_cmd

        mock_config.PY3K = default_vs != '9.0'
        mock_config.use_MSVC2015 = default_vs == '14.0'

        # this will throw an exception if the subprocess return code is not 0
        #     this is effectively the test condition for all below tests.
        with open('tmp_call.bat', "w") as f:
            f.write(msvc_env_cmd(bits))
            f.write('\nif not "%VS_VERSION%" == "{}" exit /b 1'.format(default_vs))
        try:
            subprocess.check_call(['cmd.exe', '/C', 'tmp_call.bat'], shell=True)
        except subprocess.CalledProcessError:
            print("failed activation: {}, {}".format(bits, compiler))
            raise
        finally:
            os.remove('tmp_call.bat')
