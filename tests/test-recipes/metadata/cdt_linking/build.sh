#!/usr/bin/env bash

set -x

# Simple test that CDT packages can be linked
# Compile a minimal program that links against X11 and OpenGL from CDT packages
echo -e "#include <GL/gl.h>\n#include <X11/Xlib.h>\nint main() { Display *d = XOpenDisplay(NULL); glBegin(GL_TRIANGLES); glEnd(); if (d) XCloseDisplay(d); return 0; }">gl.c
${CC} -o ${PREFIX}/bin/links-to-opengl-cdt -x c -I${PREFIX}/include -L${PREFIX}/lib -lGL -lX11 -Wl,-rpath-link,${PREFIX}/lib gl.c
find ${PREFIX} -name "libGL*"
find ${PREFIX} -name "libc.so*"
