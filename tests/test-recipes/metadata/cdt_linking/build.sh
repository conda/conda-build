#!/usr/bin/env bash

set -x

# Simple test that CDT packages can be linked
# Compile a minimal program that links against X11 from CDT packages
echo -e "#include <X11/Xlib.h>\nint main() { Display *d = XOpenDisplay(NULL); if (d) XCloseDisplay(d); return 0; }">x11_test.c
${CC} -o ${PREFIX}/bin/links-to-x11-cdt -x c -I${PREFIX}/include -L${PREFIX}/lib -lX11 -Wl,-rpath-link,${PREFIX}/lib x11_test.c
find ${PREFIX} -name "libX11*"
find ${PREFIX} -name "libc.so*"
