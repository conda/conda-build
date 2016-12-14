import os

out_path = os.path.join(os.environ['PREFIX'], 'subpackage_file_1')

with open(out_path, 'w') as f:
    f.write("weeee")

# need to write output files to a file.  Hokey, but only cross-language way to collect this.
#    One file per line.  Make sure this filename is right - conda-build looks for it.
with open(os.path.basename(__file__).replace('.py', '.txt'), 'a') as f:
    f.write(out_path + "\n")
