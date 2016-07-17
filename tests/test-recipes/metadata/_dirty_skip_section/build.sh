# ensure that the DIRTY environment variable is available for logic in build scripts
[ -n "$DIRTY" ] && exit 0
exit 1
