import os

print(os.getenv('PREFIX'))
filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1')
assert os.path.isfile(filename)
assert open(filename).read().rstrip() == "weee"
print("plain file OK")

filename = os.path.join(os.environ['PREFIX'], 'somedir', 'subpackage_file1')
assert os.path.isfile(filename)
assert open(filename).read().rstrip() == "weee"
print("subfolder file OK")

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1.ext')
assert os.path.isfile(filename)
assert open(filename).read().rstrip() == "weee"


filename = os.path.join(os.environ['PREFIX'], 'subpackage_file2.ext')
assert os.path.isfile(filename)
assert open(filename).read().rstrip() == "weee"
print("glob OK")
