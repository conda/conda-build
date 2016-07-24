import os

print("Tests run OK")
# test2 is not a checked-in file.  It is written by the test, and removed after being run.
test2 = os.path.join(os.path.dirname(__file__), 'test2.py')
assert os.path.isfile(test2), os.listdir(os.path.dirname(__file__))
