import os
import subprocess

from .utils import testing_workdir

def test_skeleton_pypi(testing_workdir):
    """published in docs at http://conda.pydata.org/docs/build_tutorials/pkgs.html"""
    cmd = 'conda skeleton pypi pyinstrument'
    subprocess.check_call(cmd.split())
    cmd = 'conda build pyinstrument'
    subprocess.check_call(cmd.split())
