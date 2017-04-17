import os

assert os.getenv('PERL')
assert os.getenv('PERL_VER')
assert os.getenv('CONDA_PERL')
assert not os.getenv('R')
assert not os.getenv('LUA')
# python is allowed, because it's present to run this script.
# assert not os.getenv('PYTHON')
