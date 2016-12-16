import os

print(os.getenv('PREFIX'))
filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert "weee" in contents, 'incorrect file contents: %s' % contents
print("plain file OK")

filename = os.path.join(os.environ['PREFIX'], 'somedir', 'subpackage_file1')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert "weee" in contents, 'incorrect file contents: %s' % contents
print("subfolder file OK")

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1.ext')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert "weee" in contents, 'incorrect file contents: %s' % contents

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file2.ext')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert "weee" in contents, 'incorrect file contents: %s' % contents
print("glob OK")
