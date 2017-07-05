import os

assert os.getenv('LUA')
assert os.getenv('LUA_VER')
assert os.getenv('CONDA_LUA')
assert os.getenv('LUA_INCLUDE_DIR')
assert not os.getenv('R')
assert not os.getenv('PERL')
# python is allowed, because it's present to run this script.
# assert not os.getenv('PYTHON')
