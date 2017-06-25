# (c) 2012-2017 Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

"""
Tools for converting conda packages

"""
import glob
import json
import hashlib
import os
import re
import shutil
import sys
import tarfile
import tempfile


def retrieve_c_extensions(file_path, show_imports=False):
    """Check tarfile for compiled C files with '.pyd' or '.so' suffixes.

    If a file ends in either .pyd or .so, it is a compiled C file.
    Because compiled C code varies between platforms, it is not possible
    to convert packages containing C extensions to other platforms.

    Positional arguments:
    file_path (str) -- the file path to the source package tar file

    Keyword arguments:
    show_imports (bool) -- output the C extensions included in the package
    """
    c_extension_pattern = re.compile(
        r'(Lib\/|lib\/python\d\.\d\/|lib\/)(site-packages\/|lib-dynload)?(.*)')

    imports = []
    with tarfile.open(file_path) as tar:
        for filename in tar.getnames():
            if filename.endswith(('.pyd', '.so')):
                filename_match = c_extension_pattern.match(filename)
                import_name = 'import {}' .format(filename_match.group(3).replace('/', '.'))
                imports.append(import_name)

    return imports


def retrieve_package_platform(file_path):
    """Retrieve the platform and architecture of the source package.

    Positional arguments:
    file_path (str) -- the file path to the source package tar file
    """
    with tarfile.open(file_path) as tar:
        index = json.loads(tar.extractfile('info/index.json').read().decode('utf-8'))

    platform = index['platform']
    architecture = '64' if index['arch'] == 'x86_64' else '32'

    if platform.startswith('linux') or platform.startswith('osx'):
        return ('unix', platform, architecture)
    elif index['platform'].startswith('win'):
        return ('win', platform, architecture)
    else:
        raise RuntimeError('Package platform not recognized.')


def retrieve_python_version(file_path):
    """Retrieve the python version from a path.

    This function is overloaded to handle three separate cases:
    when a path is a tar archive member path such as 'lib/python3.6/site-packages',
    when a path is the file path to the source package tar file, and when a path
    is the path to the temporary directory that contains the extracted contents
    of the source package tar file. This allows one function to handle the three
    most common cases of retrieving the python version from the source package.

    Positional arguments:
    file_path (str) -- the file path to a tar archive member, the file path
        to the source tar file itself, or the file path to the
        temporary directory containing the extracted source package contents
    """
    if 'python' in file_path:
        pattern = re.compile(r'python\d\.\d')
        matched = pattern.search(file_path)

        if matched:
            return matched.group(0)

    else:
        if file_path.endswith(('.tar.bz2', '.tar')):
            with tarfile.open(file_path) as tar:
                index = json.loads(tar.extractfile('info/index.json').read().decode('utf-8'))

        else:
            path_file = os.path.join(file_path, 'info/index.json')

            with open(path_file) as index_file:
                index = json.load(index_file)

        build_version_number = re.search('(.*)?(py)(\d\d)(.*)?', index['build']).group(3)
        build_version = re.sub('\A.*py\d\d.*\Z', 'python', index['build'])

        return '{}{}.{}' .format(build_version,
            build_version_number[0], build_version_number[1])


def extract_temporary_directory(file_path):
    """Extract the source tar archive contents to a temporary directory.

    Positional arguments:
    file_path (str) -- the file path to the source package tar file
    """
    temporary_directory = tempfile.mkdtemp()

    source = tarfile.open(file_path)
    source.extractall(temporary_directory)
    source.close()

    return temporary_directory


def update_dependencies(new_dependencies, existing_dependencies):
    """Update the source package's existing dependencies.

    When a user passes additional dependencies from the command line,
    these dependencies will be added to the source package's existing dependencies.
    If the dependencies passed from the command line are existing dependencies,
    these existing dependencies are overwritten.

    Positional arguments:
    new_dependencies (List[str]) -- the dependencies passed from the command line
    existing_dependencies (List[str]) -- the dependencies found in the source
        package's index.json file
    """
    # split dependencies away from their version numbers since we need the names
    # in order to evaluate duplication
    dependency_names = set(dependency.split()[0] for dependency in new_dependencies)
    index_dependency_names = set(index.split()[0] for index in existing_dependencies)

    repeated_packages = index_dependency_names.intersection(dependency_names)

    if len(repeated_packages) > 0:
        for index_dependency in existing_dependencies:
            for dependency in repeated_packages:
                if index_dependency.startswith(dependency):
                    existing_dependencies.remove(index_dependency)

    existing_dependencies.extend(new_dependencies)

    return existing_dependencies


def update_index_file(temp_dir, target_platform, dependencies, verbose):
    """Update the source package's index file with the target platform's information.

    Positional arguments:
    temp_dir (str) -- the file path to the temporary directory that contains
        the source package's extracted contents
    target_platform (str) -- the target platform and architecture in
        the form of platform-architecture such as linux-64
    dependencies (List[str]) -- the dependencies passed from the command line
    verbose (bool) -- show output of items that are updated
    """
    index_file = os.path.join(temp_dir, 'info/index.json')

    with open(index_file) as file:
        index = json.load(file)

    platform, architecture = target_platform.split('-')
    source_architecture = '64' if index['arch'] == 'x86_64' else '32'

    if verbose:
        print('Updating platform from {} to {}' .format(index['platform'], platform))
        print('Updating subdir from {} to {}' .format(index['subdir'], target_platform))
        print('Updating architecture from {} to {}' .format(source_architecture, architecture))

    index['platform'] = platform
    index['subdir'] = target_platform
    index['arch'] = 'x86_64' if architecture == '64' else 'x86'

    if dependencies:
        index['depends'] = update_dependencies(dependencies, index['depends'])

    with open(index_file, 'w') as file:
        json.dump(index, file)

    return index_file


def update_lib_path(path, target_platform, temp_dir=None):
    """Update the lib path found in the source package's paths.json file.

    For conversions from unix to windows, the 'lib/pythonx.y/' paths are
    renamed to 'Lib/' and vice versa for conversions from windows to unix.

    Positional arguments:
    path (str) -- path to rename in the paths.json file
    target_platform (str) -- the platform to target: 'unix' or 'win'

    Keyword arguments:
    temp_dir (str) -- the file path to the temporary directory that
        contains the source package's extracted contents
    """
    if target_platform == 'win':
        python_version = retrieve_python_version(path)
        renamed_lib_path = re.sub('\Alib', 'Lib', path).replace(python_version, '')

    elif target_platform == 'unix':
        python_version = retrieve_python_version(temp_dir)
        renamed_lib_path = re.sub('\ALib', os.path.join('lib', python_version), path)

    return os.path.normpath(renamed_lib_path)


def update_lib_contents(lib_directory, temp_dir, target_platform, file_path):
    """Update the source package's 'lib' directory.

    When converting from unix to windows, the 'lib' directory is renamed to
    'Lib' and the contents inside the 'pythonx.y' directory are renamed to
    exclude the 'pythonx.y' prefix. When converting from windows to unix,
    the 'Lib' is renamed to 'lib' and the pythonx.y' prefix is added.

    Positional arguments:
    lib_directory (str) -- the file path to the 'lib' directory located in the
        temporary directory that stores the package contents
    temp_dir (str) -- the file path to the temporary directory that contains
        the source package's extracted contents
    target_platform (str) -- the platform to target: 'unix' or win'
    file_path (str) -- the file path to the source package tar file
    """
    if target_platform == 'win':
        try:
            for lib_file in glob.iglob('{}/python*/**' .format(lib_directory)):
                if 'site-packages' in lib_file:
                    new_site_packages_path = os.path.join(temp_dir, 'lib/site-packages')
                    os.renames(lib_file, new_site_packages_path)
                else:
                    if retrieve_python_version(lib_file) is not None:
                        python_version = retrieve_python_version(lib_file)
                        os.renames(lib_file, lib_file.replace(python_version, ''))
        except OSError:
            pass

        try:
            shutil.rmtree(glob.glob('{}/python*' .format(lib_directory))[0])
        except IndexError:
            pass

        os.rename(os.path.join(temp_dir, 'lib'), os.path.join(temp_dir, 'Lib'))

    elif target_platform == 'unix':
        try:
            for lib_file in glob.iglob('{}/**' .format(lib_directory)):
                python_version = retrieve_python_version(file_path)
                new_lib_file = re.sub('Lib', os.path.join('lib', python_version), lib_file)
                os.renames(lib_file, new_lib_file)

            os.rename(os.path.join(temp_dir, 'Lib'), os.path.join(temp_dir, 'lib'))

        except OSError:
            pass


def update_executable_path(file_path, target_platform):
    """Update the name of the executable files found in the paths.json file.

    When converting from unix to windows, executables are renamed with a '-script.py'
    suffix. When converting from windows to unix, this suffix is removed. The
    paths in paths.json need to be updated accordingly.

    Positional arguments:
    file_path (str) -- the file path to the executable to rename in paths.json
    target_platform (str) -- the platform to target: 'unix' or 'win'
    """
    if target_platform == 'win':
        renamed_path = os.path.splitext(re.sub('\Abin', 'Scripts', file_path))[0]
        renamed_executable_path = '{}-script.py' .format(renamed_path)

    elif target_platform == 'unix':
        renamed_path = os.path.splitext(re.sub('\AScripts', 'bin', file_path))[0]
        renamed_executable_path = renamed_path.replace('-script.py', '')

    return renamed_executable_path


def add_new_windows_path(executable_directory, executable):
    """Add a new path to the paths.json file.

    When an executable is renamed during a unix to windows conversion, a
    an exe is also created. The paths.json file is updated with the
    exe file's information.

    Positional arguments:
    executable_directory (str) -- the file path to temporary directory's 'Scripts' directory
    executable (str) -- the filename of the script to add to paths.json
    """
    with open(os.path.join(executable_directory, executable), 'rb') as script_file:
        script_file_contents = script_file.read()
        new_path = {"_path": "Scripts/{}" .format(executable),
                    "path_type": "hardlink",
                    "sha256": hashlib.sha256(script_file_contents).hexdigest(),
                    "size_in_bytes": os.path.getsize(
                        os.path.join(executable_directory, executable))
                    }
    return new_path


def update_paths_file(temp_dir, target_platform):
    """Update the paths.json file when converting between platforms.

    Positional arguments:
    temp_dir (str) -- the file path to the temporary directory containing the source
        package's extracted contents
    target_platform (str) -- the platform to target: 'unix' or 'win'
    """
    paths_file = os.path.join(temp_dir, 'info/paths.json')

    if os.path.isfile(paths_file):
        with open(paths_file) as file:
            paths = json.load(file)

        if target_platform == 'win':
            for path in paths['paths']:
                if path['_path'].startswith('lib'):
                    path['_path'] = update_lib_path(path['_path'], 'win')

                elif path['_path'].startswith('bin'):
                    path['_path'] = update_executable_path(path['_path'], 'win')

            script_directory = os.path.join(temp_dir, 'Scripts')
            if os.path.isdir(script_directory):
                for script in os.listdir(script_directory):
                    if script.endswith('.exe'):
                        paths['paths'].append(add_new_windows_path(script_directory, script))

        elif target_platform == 'unix':
            for path in paths['paths']:
                if path['_path'].startswith('Lib'):
                    path['_path'] = update_lib_path(path['_path'], 'unix', temp_dir)

                elif path['_path'].startswith('Scripts'):
                    path['_path'] = update_executable_path(path['_path'], 'unix')

                if path['_path'].endswith(('.bat', '.exe')):
                    paths['paths'].remove(path)

        with open(paths_file, 'w') as file:
            json.dump(paths, file)


def retrieve_executable_name(executable):
    """Retrieve the name of the executable to rename.

    When converting between unix and windows, we need to be careful
    that the executables are renamed without their file extensions.

    Positional arguments:
    executable (str) -- the executable to rename including its file extension
    """
    return os.path.splitext(os.path.basename(executable))[0]


def is_binary_file(directory, executable):
    """Read a file's contents to check whether it is a binary file.

    When converting files, we need to check that binary files are not
    converted.

    Source: https://stackoverflow.com/questions/898669/

    Positional arguments:
    directory (str) -- the file path to the 'bin' or 'Scripts' directory
    executable (str) -- the name of the executable to rename
    """
    file_path = os.path.join(directory, executable)

    if os.path.isfile(file_path):
        with open(file_path, 'rb') as buffered_file:
            file_contents = buffered_file.read(1024)

        text_characters = bytearray({7, 8, 9, 10, 12, 13, 27}.union(
            set(range(0x20, 0x100)) - {0x7f}))

        return bool(file_contents.translate(None, text_characters))

    return False


def rename_executable(directory, executable, target_platform):
    """Rename an executable file when converting between platforms.

    When converting from unix to windows, each file inside the 'bin' directory
    is renamed to include '-script.py' as a suffix. When converting from windows
    to unix, each executable inside the 'Scripts' directory has its '-script.py'
    suffix removed.

    Positional arguments:
    directory (str) -- the file path to the 'bin' or 'Scripts' directory
    executable (str) -- the name of the executable to rename
    target_platform (str) -- the platform to target: 'unix' or 'win'
    """
    old_executable_path = os.path.join(directory, executable)

    if target_platform == 'win':
        new_executable_path = os.path.join(directory, '{}-script.py' .format(
            retrieve_executable_name(executable)))

        with open(old_executable_path) as script_file_in:
            lines = script_file_in.read().splitlines()

        with open(old_executable_path, 'w') as script_file_out:
            for line in lines[1:]:
                script_file_out.write(line + '\n')

        os.renames(old_executable_path, new_executable_path)

    else:
        if old_executable_path.endswith('.py'):

            new_executable_path = old_executable_path.replace('-script.py', '')

            with open(old_executable_path) as script_file_in:
                lines = script_file_in.read().splitlines()

            with open(old_executable_path, 'w') as script_file_out:
                script_file_out.write('#!/opt/anaconda1anaconda2anaconda3/bin/python' + '\n')
                for line in lines:
                    script_file_out.write(line + '\n')

            os.renames(old_executable_path, new_executable_path)


def remove_executable(directory, executable):
    """Remove an executable from the 'Scripts' directory.

    When converting from windows to unix, the .exe or .bat files
    need to be removed as they do not exist in unix packages.

    Positional arguments:
    directory (str) -- the file path to the 'Scripts' directory
    executable (str) -- the filename of the executable to remove
    """
    if executable.endswith(('.exe', '.bat')):
        script = os.path.join(directory, executable)
        os.remove(script)


def create_exe_file(directory, executable, target_platform):
    """Create an exe file for each executable during a unix to windows conversion.

    Positional arguments:
    directory (str) -- the file path to the 'Scripts' directory
    executable (str) -- the filename of the executable to create an exe file for
    target_platform -- the platform to target: 'win-64' or 'win-32'
    """
    exe_directory = os.path.dirname(__file__)

    if target_platform.endswith('32'):
        executable_file = os.path.join(exe_directory, 'cli-32.exe')

    else:
        executable_file = os.path.join(exe_directory, 'cli-64.exe')

    renamed_executable_file = os.path.join(directory, '{}.exe' .format(executable))

    shutil.copyfile(executable_file, renamed_executable_file)


def update_prefix_file(temp_dir, prefixes):
    """Update the source package's 'has_prefix' file.

    Each file in the 'bin' or 'Scripts' folder will be written
    to the 'has_prefix' file located in the package's 'info' directory.

    Positional arguments:
    temp_dir (str) -- the file path to the temporary directory containing the source
        package's extracted contents
    prefixes (List[str])-- the prefixes to write to 'has_prefix'
    """
    has_prefix_file = os.path.join(temp_dir, 'info/has_prefix')

    with open(has_prefix_file, 'w+') as prefix_file:
        for prefix in prefixes:
            prefix_file.write(prefix)


def update_files_file(temp_dir, verbose):
    """Update the source package's 'files' file.

    The file path to each file that will be in the target archive is
    written to the 'files' file.

    Positional arguments:
    temp_dir (str) -- the file path to the temporary directory containing the source
        package's extracted contents
    verbose (bool) -- show output of items that are updated
    """
    files_file = os.path.join(temp_dir, 'info/files')

    with open(files_file, 'w+') as files:
        for dirpath, dirnames, filenames in os.walk(temp_dir):
            for filename in filenames:
                package_file_path = os.path.join(
                    dirpath, filename).replace(temp_dir, '').lstrip(os.sep)
                if not package_file_path.startswith('info'):
                    files.write(package_file_path + '\n')

                    if verbose:
                        print('Updating {}' .format(package_file_path))


def create_target_archive(file_path, temp_dir, platform, output_dir):
    """Create the converted package's tar file.

    Positional arguments:
    file_path (str) -- the file path to the source package's tar file
    temp_dir (str) -- the file path to the temporary directory containing the source
        package's extracted contents
    platform (str) -- the platform to convert to: 'win-64', 'win-32', 'linux-64',
        'linux-32', or 'osx-64'
    """
    output_directory = os.path.join(output_dir, platform)

    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)

    destination = os.path.join(output_directory, os.path.basename(file_path))

    with tarfile.open(destination, 'w:bz2') as target:
        for dirpath, dirnames, filenames in os.walk(temp_dir):
            for filename in filenames:
                destination_file_path = os.path.join(
                    dirpath, filename).replace(temp_dir, '').lstrip(os.sep)
                target.add(os.path.join(dirpath, filename), arcname=destination_file_path)


def convert_between_unix_platforms(file_path, output_dir, platform, dependencies, verbose):
    """Convert package between unix platforms.

    Positional arguments:
    file_path (str) -- the file path to the source package's tar file
    output_dir (str) -- the file path to where to output the converted tar file
    platform (str) -- the platform to convert to: 'linux-64', 'linux-32', or 'osx-64'
    dependencies (List[str]) -- the dependencies passed from the command line
    verbose (bool) -- show output of items that are updated
    """
    temp_dir = extract_temporary_directory(file_path)

    update_index_file(temp_dir, platform, dependencies, verbose)

    create_target_archive(file_path, temp_dir, platform, output_dir)

    # we need to manually remove the temporary directory created by tempfile.mkdtemp
    shutil.rmtree(temp_dir)


def convert_between_windows_architechtures(file_path, output_dir, platform,
                                           dependencies, verbose):
    """Convert package between windows architectures.

    Positional arguments:
    file_path (str) -- the file path to the source package's tar file
    output_dir (str) -- the file path to where to output the converted tar file
    platform (str) -- the platform to convert to: 'win-64' or 'win-32'
    dependencies (List[str]) -- the dependencies passed from the command line
    verbose (bool) -- show output of items that are updated
    """
    temp_dir = extract_temporary_directory(file_path)

    update_index_file(temp_dir, platform, dependencies, verbose)

    create_target_archive(file_path, temp_dir, platform, output_dir)

    # we need to manually remove the temporary directory created by tempfile.mkdtemp
    shutil.rmtree(temp_dir)


def convert_from_unix_to_windows(file_path, output_dir, platform, dependencies, verbose):
    """Convert a package from a unix platform to windows.

    Positional arguments:
    file_path (str) -- the file path to the source package's tar file
    output_dir (str) -- the file path to where to output the converted tar file
    platform (str) -- the platform to convert to: 'win-64' or 'win-32'
    dependencies (List[str]) -- the dependencies passed from the command line
    verbose (bool) -- show output of items that are updated
    """
    temp_dir = extract_temporary_directory(file_path)

    prefixes = set()

    for entry in os.listdir(temp_dir):
        directory = os.path.join(temp_dir, entry)
        if os.path.isdir(directory) and entry.strip(os.sep) == 'lib':
            update_lib_contents(directory, temp_dir, 'win', file_path)

        if os.path.isdir(directory) and entry.strip(os.sep) == 'bin':
            for script in os.listdir(directory):
                if not is_binary_file(directory, script) and not script.startswith('.'):
                    rename_executable(directory, script, 'win')
                    create_exe_file(directory, retrieve_executable_name(script),
                                      platform)

                    prefixes.add('/opt/anaconda1anaconda2anaconda3 text Scripts/{}-script.py\n'
                        .format(retrieve_executable_name(script)))

            new_bin_path = os.path.join(temp_dir, 'Scripts')
            os.renames(directory, new_bin_path)

    update_index_file(temp_dir, platform, dependencies, verbose)
    update_prefix_file(temp_dir, prefixes)
    update_paths_file(temp_dir, target_platform='win')
    update_files_file(temp_dir, verbose)

    create_target_archive(file_path, temp_dir, platform, output_dir)

    shutil.rmtree(temp_dir)


def convert_from_windows_to_unix(file_path, output_dir, platform, dependencies, verbose):
    """Convert a package from windows to a unix platform.

    Positional arguments:
    file_path (str) -- the file path to the source package's tar file
    output_dir (str) -- the file path to where to output the converted tar file
    platform (str) -- the platform to convert to: 'linux-64', 'linux-32', or 'osx-64'
    dependencies (List[str]) -- the dependencies passed from the command line
    verbose (bool) -- show output of items that are updated
    """
    retrieve_python_version(file_path)
    temp_dir = extract_temporary_directory(file_path)

    prefixes = set()

    for entry in os.listdir(temp_dir):
        directory = os.path.join(temp_dir, entry)
        if os.path.isdir(directory) and 'Lib' in directory:
            update_lib_contents(directory, temp_dir, 'unix', file_path)

        if os.path.isdir(directory) and 'Scripts' in directory:
            for script in os.listdir(directory):
                if not is_binary_file(directory, script) and not script.startswith('.'):
                    rename_executable(directory, script, 'unix')
                    remove_executable(directory, script)

                    prefixes.add('/opt/anaconda1anaconda2anaconda3 text bin/{}\n'
                        .format(retrieve_executable_name(script)))

            new_bin_path = os.path.join(temp_dir, 'bin')
            os.renames(directory, new_bin_path)

    update_index_file(temp_dir, platform, dependencies, verbose)
    update_prefix_file(temp_dir, prefixes)
    update_paths_file(temp_dir, target_platform='unix')
    update_files_file(temp_dir, verbose)

    create_target_archive(file_path, temp_dir, platform, output_dir)

    shutil.rmtree(temp_dir)


def conda_convert(file_path, output_dir=".", show_imports=False, platforms=None, force=False,
                  dependencies=None, verbose=False, quiet=False, dry_run=False):
    """Convert a conda package between different platforms and architectures.

    Positional arguments:
    file_path (str) -- the file path to the source package's tar file
    output_dir (str) -- the file path to where to output the converted tar file
    show_imports (bool) -- show all C extensions found in the source package
    platforms (str) -- the platforms to convert to: 'win-64', 'win-32', 'linux-64',
        'linux-32', 'osx-64', or 'all'
    force (bool) -- force conversion of packages that contain C extensions
    dependencies (List[str]) -- the new dependencies to add to the source package's
        existing dependencies
    verbose (bool) -- show output of items that are updated
    quiet (bool) -- hide all output except warnings and errors
    dry_run (bool) -- show which conversions will take place
    """
    if show_imports:
        imports = retrieve_c_extensions(file_path)
        if len(imports) == 0:
            print('No imports found.')
        else:
            for c_extension in imports:
                print(c_extension)
        sys.exit()

    if not show_imports and len(platforms) == 0:
        sys.exit('Error: --platform option required for conda package conversion.')

    if len(retrieve_c_extensions(file_path)) > 0 and not force:
        sys.exit('WARNING: Package {} contains C extensions; skipping conversion. '
                 'Use -f to force conversion.' .format(os.path.basename(file_path)))

    conversion_platform, source_platform, architecture = retrieve_package_platform(file_path)
    source_platform_architecture = '{}-{}' .format(source_platform, architecture)

    if 'all' in platforms:
        platforms = ['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64']

    for platform in platforms:

        if platform == source_platform_architecture:
            print("Source platform '{}' and target platform '{}' are identical. "
                  "Skipping conversion." .format(source_platform_architecture, platform))
            continue

        if not quiet:
            print('Converting {} from {} to {}' .format(
                    os.path.basename(file_path), source_platform_architecture, platform))

        if platform.startswith(('osx', 'linux')) and conversion_platform == 'unix':
            convert_between_unix_platforms(file_path, output_dir, platform,
                                           dependencies, verbose)

        elif platform.startswith('win') and conversion_platform == 'unix':
            convert_from_unix_to_windows(file_path, output_dir, platform,
                                         dependencies, verbose)

        elif platform.startswith(('osx', 'linux')) and conversion_platform == 'win':
            convert_from_windows_to_unix(file_path, output_dir, platform,
                                         dependencies, verbose)

        elif platform.startswith('win') and conversion_platform == 'win':
            convert_between_windows_architechtures(file_path, output_dir, platform,
                                                   dependencies, verbose)
