import os

with open(os.path.join(os.environ['PREFIX'], 'subpackage_file_1'), 'w') as f:
    f.write("weeee")
