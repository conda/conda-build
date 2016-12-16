import os

PREFIX = os.environ["PREFIX"]

with open(os.path.join(PREFIX, 'conda-build-test')) as f:
    SRC_DIR = f.read().strip()

assert not os.path.exists(SRC_DIR), SRC_DIR
