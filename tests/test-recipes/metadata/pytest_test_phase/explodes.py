import pytest
import time

@pytest.mark.parametrize('iteration', range(100))
def test_foo(tmpdir, iteration):
    tmpdir.chdir()
    tmpdir.remove()
    print("removed dir out from under self.  Crashing?")
    time.sleep(0.1)

    assert True, 'yep'
