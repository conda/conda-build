import sys
import os
import os.path

from conda_build.os_utils.external import find_executable

def test_find_executable(testing_workdir, monkeypatch):
    if sys.platform != "win32":
        import stat

        path_components = []

        def create_file(unix_path, put_on_path, executable):
            localized_path = os.path.join(testing_workdir, *unix_path.split('/'))
            # empty prefix by default - extra bit at beginning of file
            if sys.platform == "win32":
                localized_path = localized_path + ".bat"

            dirname = os.path.split(localized_path)[0]
            if not os.path.isdir(dirname):
                os.makedirs(dirname)

            if sys.platform == "win32":
                prefix = "@echo off\n"
            else:
                prefix = "#!/bin/bash\nexec 1>&2\n"
            with open(localized_path, 'w') as f:
                f.write(prefix + """
            echo ******* You have reached the dummy {}. It is likely there is a bug in
            echo ******* conda that makes it not add the _build/bin directory onto the
            echo ******* PATH before running the source checkout tool
            exit -1
            """.format(localized_path))

            if put_on_path:
                path_components.append(dirname)

            if executable:
                st = os.stat(localized_path)
                os.chmod(localized_path, st.st_mode | stat.S_IEXEC)

            return localized_path

        create_file('executable/not/on/path/with/target_name', put_on_path=False, executable=True)
        create_file('non_executable/on/path/with/target_name', put_on_path=True, executable=False)
        create_file('executable/on/path/with/non_target_name', put_on_path=True, executable=True)
        target_path = create_file('executable/on/path/with/target_name', put_on_path=True, executable=True)
        create_file('another/executable/later/on/path/with/target_name', put_on_path=True, executable=True)

        monkeypatch.setenv('PATH', os.pathsep.join(path_components))

        find = find_executable('target_name')

        assert find == target_path, "Expected to find 'target_name' in '%s', but found it in '%s'" % (target_path, find)
