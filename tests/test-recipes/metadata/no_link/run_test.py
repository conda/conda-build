import os
f = os.path.join(os.getenv('PREFIX'), 'no_link_file.example')
assert os.path.isfile(f), "File does not exist"
assert os.stat(f).st_nlink <= 1, "File is hard-linked where it should not be (link count = {})".format(os.stat(f).st_nlink)
assert not os.path.islink(f), "File is a symlink where it should not be"
