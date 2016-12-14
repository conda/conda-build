import os

print(os.getenv('PREFIX'))
filename = os.path.join(os.getenv('PREFIX'), 'subpackage_file_1')

assert os.path.isfile(filename)
assert open(filename).read() == "weeee"
