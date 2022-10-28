#!/usr/bin/env bash

set -x

echo -e "#include <GL/gl.h>\nint main() { glBegin(GL_TRIANGLES); glEnd(); return 0; }">gl.c
${CC} -o ${PREFIX}/bin/links-to-opengl-cdt -x c $(pkg-config --libs gl) -Wl,-rpath-link,${PREFIX}/lib gl.c
find ${PREFIX} -name "libGL*"
find ${PREFIX} -name "libc.so*"
