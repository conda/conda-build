import unittest
import os

from conda_build.windows import msvc_env_cmd

import pytest

if 'ProgramFiles(x86)' in os.environ:
    program_files = os.environ['ProgramFiles(x86)']
else:
    program_files = os.environ['ProgramFiles']

vcvars_backup_files = {"vs{}".format(version): os.path.join(program_files,
                              r'Microsoft Visual Studio {version}'.format(version=version),
                              'VC', 'vcvarsall.bat') for version in ["9.0", "10.0"]}
# VC9 compiler for python - local user install
localappdata = os.environ.get("localappdata")
vcvars_backup_files["python_local"]=os.path.join(localappdata, 'Programs', 'Common',
                'Microsoft', 'Visual C++ for Python', "9.0", "vcvarsall.bat")
# VC9 compiler for python - common files
vcvars_backup_files["python_system"] = os.path.join(program_files, 'Common Files',
                'Microsoft', 'Visual C++ for Python', "9.0", "vcvarsall.bat")
# Windows SDK 7.1
vcvars_backup_files["win71sdk"] = "{program_files}\\Microsoft SDKs\\Windows\\v7.1\\Bin\\SetEnv.cmd".\
                                  format(program_files=program_files)


def write_bat_files(good_locations):
    for label, location in vcvars_backup_files.items():
        assert not os.path.exists(location)  # these should all have been moved!  bad to overwrite them!
        os.makedirs(os.path.dirname(location))  # not currently cleaned up.  Sorry.
        with open(location, "w") as f:
            f.write("exit {}".format(int(label in good_locations)))


def call_subprocess_activate(bits, vcver):
    cmd = msvc_env_cmd(bits, vcver)
    # this will throw an exception if the subprocess return code is not 0
    #     this is effectively the test condition for all below tests.
    subprocess.check_call(cmd)


@pytest.fixture(scope="function", params=vcvars_backup_files.keys())
def bat(request):
    for f in vcvars_backup_files:
        if os.path.exists(f):
            os.rename(f, f[:-1]+'k')
    write_bat_files([request.param])
    def fin():
        print ("teardown bat")
        for f in vcvars_backup_files:
            # clean up any of the custom scripts we wrote to test
            if os.path.exists(f):
                os.remove(f)
            # restore the backups
            if os.path.exists(f[:-1]+'k'):
                os.rename(f[:-1]+'k', f)
    request.addfinalizer(fin)
    return request.param


@pytest.fixture(params=[32, 64])
def bits(request):
    return request.param


def test_activation(bits, bat):
    call_subprocess_activate(bats.bits, bats.location)
