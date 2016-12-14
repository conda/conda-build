import os

out_path = os.path.join(os.environ['PREFIX'], 'subpackage_file_1')

with open(out_path, 'w') as f:
    f.write("weeee")
