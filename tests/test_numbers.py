import numpy as np
from src.numbers import FixedReader, NumberReader

def test_fixed_reader_returns_value():
    r = FixedReader(251)
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert r.read(img, (0, 0, 5, 5)) == 251

def test_fixed_reader_is_number_reader():
    r: NumberReader = FixedReader(0)
    assert hasattr(r, "read")
