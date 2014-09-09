# We test the environment variables in a different recipe

# Ensure we are in a git repo
[ -d trunk ]
cd trunk
svn info
[ "$(svn info | grep "Revision")" = "Revision: 1157" ]
# PYTHONPATH=. python -c "import conda_build; assert conda_build.__version__ == '1.8.1'"
# No way to test the version because it's computed by versioneer, which uses git
