import os

assert os.getenv('PYTHON')
assert os.getenv('PY_VER')
assert os.getenv('CONDA_PY')
assert os.getenv('STDLIB_DIR')
assert os.getenv('SP_DIR')
assert os.getenv('PY3K')
assert not os.getenv('PERL')
assert not os.getenv('R')
assert not os.getenv('LUA')
