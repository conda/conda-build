import os
import sys

assert os.path.exists(os.getenv('PYTHON'))
assert os.getenv('PY_VER')
assert os.getenv('CONDA_PY')
assert '.' not in os.getenv('CONDA_PY')
assert os.path.exists(os.getenv('STDLIB_DIR'))
assert os.path.exists(os.getenv('SP_DIR'))
assert os.getenv('PY3K')
assert not os.getenv('PERL'), os.getenv('PERL')
assert not os.getenv('R'), os.getenv('R')
assert not os.getenv('LUA'), os.getenv('LUA')

if sys.platform == 'win32':
    assert os.path.dirname(os.getenv('PYTHON')) == os.path.dirname(os.getenv('LIBRARY_PREFIX'))
