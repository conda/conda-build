def test_foo(tmpdir):
    tmpdir.chdir()
    tmpdir.remove()
    print("removed dir out from under self.  Crashing?")

    assert True, 'yep'
