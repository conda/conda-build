import os

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1')
assert os.path.isfile(filename)
assert open(filename).read() == "weee"

filename = os.path.join(os.environ['PREFIX'], 'subdir', 'subpackage_file1')
assert os.path.isfile(filename)
assert open(filename).read() == "weee"

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1.ext')
assert os.path.isfile(filename)
assert open(filename).read() == "weee"


filename = os.path.join(os.environ['PREFIX'], 'subpackage_file2.ext')
assert os.path.isfile(filename)
assert open(filename).read() == "weee"
