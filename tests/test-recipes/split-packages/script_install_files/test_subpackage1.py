import os

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file_1')

assert os.path.isfile(filename)
assert open(filename).read() == "weeee"
