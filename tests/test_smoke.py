from importlib.util import find_spec


def test_aegisflow_package_is_importable() -> None:
    assert find_spec("aegisflow") is not None
