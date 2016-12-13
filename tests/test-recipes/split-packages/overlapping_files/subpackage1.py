import os

out_file = os.path.join(os.environ['PREFIX'], 'subpackage_file_1')

with open(out_file, 'w') as f:
    f.write("weeee")

print(out_file)
