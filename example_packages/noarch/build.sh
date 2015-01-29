#!/bin/bash

cp -r * $PREFIX

cat <<EOF >${PREFIX}/bin/.${PKG_NAME}-pre-link.sh
#!/bin/bash
cd \$SOURCE_DIR
\$PREFIX/bin/python setup.py install
EOF

mkdir $PREFIX/Scripts
cat <<EOF >${PREFIX}/Scripts/.${PKG_NAME}-pre-link.bat
@echo off
cd %SOURCE_DIR%
%PREFIX%/python.exe setup.py install
EOF
