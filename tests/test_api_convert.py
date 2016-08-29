import pytest

from conda_build.api import convert


def test_convert_wheel_raises():
    with pytest.raises(RuntimeError) as exc:
        convert("some_wheel.whl")
        assert "Conversion from wheel packages" in str(exc)


def test_convert_exe_raises():
    with pytest.raises(RuntimeError) as exc:
        convert("some_wheel.exe")
        assert "cannot convert:" in str(exc)
