# Ensure the checkout went well
svn info
[ "$(svn info | grep "Revision")" = "Revision: 1" ]
