import os
import subprocess

from conda.compat import TemporaryDirectory


def test_skeleton_pypi():
    """published in docs at http://conda.pydata.org/docs/build_tutorials/pkgs.html"""
    cwd = os.getcwd()
    with TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            cmd = 'conda skeleton pypi pyinstrument'
            subprocess.check_call(cmd.split())
            cmd = 'conda build pyinstrument'
            subprocess.check_call(cmd.split())
        except:
            raise
        finally:
            os.chdir(cwd)
