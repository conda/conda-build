# We test the environment variables in a different recipe

# Ensure we are in a git repo
[ -d .hg ]
hg id
[ "$(hg id)" = "6364a674cc15 test" ]
[ -e test ]
