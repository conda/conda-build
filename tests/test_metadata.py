from conda_build.metadata import select_lines

def test_select_lines():
    lines = """
test
test [abc] no

test [abc]
test # [abc]
test # [abc] yes
test # stuff [abc] yes
"""

    assert select_lines(lines, {'abc': True}) == """
test
test [abc] no

test
test
test
test
"""
    assert select_lines(lines, {'abc': False}) == """
test
test [abc] no

"""
