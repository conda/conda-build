# Ensure the checkout went well
svn upgrade
svn info
[ "$(svn info | grep "Revision")" = "Revision: 1" ]
