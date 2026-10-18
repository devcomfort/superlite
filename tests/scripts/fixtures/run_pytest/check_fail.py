import pytest


def test_ok():
    assert True


def test_broken():
    assert 1 + 1 == 3, "arithmetic is broken"


@pytest.mark.skip(reason="fixture")
def test_skipped():
    pass
