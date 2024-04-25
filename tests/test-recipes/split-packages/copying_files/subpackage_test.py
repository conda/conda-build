import os

if os.getenv("PKG_NAME") == "my_script_subpackage_files":
    file_basename = "subpackage_file"
    dirname = "somedir"
    extension = "ext"

    external_host_file = "lib/libpng16.so"
    if "osx" in os.getenv("target_platform", ""):
        external_host_file = "lib/libpng16.dylib"
    if "win" in os.getenv("target_platform", ""):
        external_host_file = "Library/bin/libpng16.dll"

    filename = os.path.join(os.environ["PREFIX"], f"{file_basename}3.{extension}")
    print(filename)
    assert os.path.isfile(filename), filename + " is missing"
    print("glob files OK")

    filename = os.path.join(os.environ["PREFIX"], external_host_file)
    print(filename)
    assert os.path.isfile(filename), filename + " is missing"
    print("glob files prefix OK")

if os.getenv("PKG_NAME") == "my_script_subpackage_include_exclude":
    file_basename = "subpackage_include_exclude"
    dirname = "anotherdir"
    extension = "wav"

    external_host_file = "lib/libdav1d.so.6"
    if "osx" in os.getenv("target_platform", ""):
        external_host_file = "lib/libdav1d.6.dylib"
    if "win" in os.getenv("target_platform", ""):
        external_host_file = "Library/bin/dav1d.dll"

    filename = os.path.join(os.environ["PREFIX"], f"{file_basename}3.{extension}")
    assert not os.path.isfile(filename), filename + " is missing"
    print("glob exclude OK")

    filename = os.path.join(os.environ["PREFIX"], external_host_file)
    assert not os.path.isfile(filename), filename + " is missing"
    print("glob exclude prefix OK")

print(os.getenv("PREFIX"))
filename = os.path.join(os.environ["PREFIX"], f"{file_basename}1")
assert os.path.isfile(filename), filename + " is missing"
contents = open(filename).read().rstrip()
if hasattr(contents, "decode"):
    contents = contents.decode()
assert "weee" in contents, "incorrect file contents: %s" % contents
print("plain file OK")

filename = os.path.join(os.environ["PREFIX"], dirname, f"{file_basename}1")
assert os.path.isfile(filename), filename + " is missing"
contents = open(filename).read().rstrip()
if hasattr(contents, "decode"):
    contents = contents.decode()
assert "weee" in contents, "incorrect file contents: %s" % contents
print("subfolder file OK")

filename = os.path.join(os.environ["PREFIX"], f"{file_basename}1.{extension}")
assert os.path.isfile(filename), filename + " is missing"
contents = open(filename).read().rstrip()
if hasattr(contents, "decode"):
    contents = contents.decode()
assert "weee" in contents, "incorrect file contents: %s" % contents

filename = os.path.join(os.environ["PREFIX"], f"{file_basename}2.{extension}")
assert os.path.isfile(filename), filename + " is missing"
contents = open(filename).read().rstrip()
if hasattr(contents, "decode"):
    contents = contents.decode()
assert "weee" in contents, "incorrect file contents: %s" % contents
print("glob OK")
