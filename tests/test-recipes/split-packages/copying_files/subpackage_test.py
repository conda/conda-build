import os

print(os.getenv('PREFIX'))
filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert 'weee' in contents, 'incorrect file contents: %s' % contents
print('plain file OK')

filename = os.path.join(os.environ['PREFIX'], 'somedir', 'subpackage_file1')
assert os.path.isfile(filename), filename + ' is missing'
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert 'weee' in contents, 'incorrect file contents: %s' % contents
print('subfolder file OK')

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file1.ext')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert 'weee' in contents, 'incorrect file contents: %s' % contents

filename = os.path.join(os.environ['PREFIX'], 'subpackage_file2.ext')
assert os.path.isfile(filename)
contents = open(filename).read().rstrip()
if hasattr(contents, 'decode'):
    contents = contents.decode()
assert 'weee' in contents, 'incorrect file contents: %s' % contents
print('glob OK')

external_host_file = 'lib/libdav1d.so.7'
if 'osx' in os.getenv('target_platform', ''):
    external_host_file = 'lib/libdav1d.7.dylib'
if 'win' in os.getenv('target_platform', ''):
    external_host_file = 'Library/bin/dav1d.dll'

if os.getenv('PKG_NAME') == 'my_script_subpackage_files':
    filename = os.path.join(os.environ['PREFIX'], 'subpackage_file3.ext')
    assert os.path.isfile(filename)
    print('glob files OK')

    filename = os.path.join(os.environ['PREFIX'], external_host_file)
    assert os.path.isfile(filename)
    print('glob files prefix OK')

if os.getenv('PKG_NAME') == 'my_script_subpackage_include_exclude':
    filename = os.path.join(os.environ['PREFIX'], 'subpackage_file3.ext')
    assert not os.path.isfile(filename)
    print('glob exclude OK')

    filename = os.path.join(os.environ['PREFIX'], external_host_file)
    assert not os.path.isfile(filename)
    print('glob exclude prefix OK')
