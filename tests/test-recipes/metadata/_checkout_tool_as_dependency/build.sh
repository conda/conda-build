# Ensure the checkout went well
# Think of the non-English speaking world
export LC_ALL=C
svn upgrade
svn info
[ "$(svn info | grep "Revision")" = "Revision: 1" ]
