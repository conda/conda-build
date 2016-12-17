import os

PREFIX = os.environ["PREFIX"]

with open(os.path.join(PREFIX, 'conda-build-test')) as f:
    SRC_DIR = f.read().strip()

# The directory might be recreated, so just check that it is empty
assert not os.path.exists(SRC_DIR) or not os.listdir(SRC_DIR), SRC_DIR
