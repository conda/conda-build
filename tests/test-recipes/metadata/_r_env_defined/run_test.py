import os

assert os.getenv('R')
assert os.getenv('R_VER')
assert os.getenv('CONDA_R')
assert not os.getenv('PERL')
assert not os.getenv('LUA')
# python is allowed, because it's present to run this script.
# assert not os.getenv('PYTHON')
