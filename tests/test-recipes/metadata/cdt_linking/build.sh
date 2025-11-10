#!/usr/bin/env bash

set -x

# Simple test that CDT packages can be linked
# Compile a minimal program that links against PAM and libselinux from CDT packages.
# This works on main channel currently, it does seem that pam-devel is missing
# on conda-forge.  In the future, we may want to change this to use so the
# test can be done on conda-forge.
cat > cdt_test.c << 'EOF'
#include <stddef.h>
#include <security/pam_appl.h>
#include <selinux/selinux.h>

int main() {
    // Test PAM - just check that the header is available
    const char *pam_strerror_result = pam_strerror(NULL, 0);
    (void)pam_strerror_result;  // Suppress unused variable warning

    // Test libselinux - check if SELinux is enabled
    int selinux_enabled = is_selinux_enabled();
    (void)selinux_enabled;  // Suppress unused variable warning

    return 0;
}
EOF

${CC} -o ${PREFIX}/bin/links-to-cdt -I${PREFIX}/include -L${PREFIX}/lib \
    -lpam -lselinux -Wl,-rpath-link,${PREFIX}/lib cdt_test.c

# Verify the libraries are present
find ${PREFIX} -name "libpam*"
find ${PREFIX} -name "libselinux*"
find ${PREFIX} -name "libc.so*"
