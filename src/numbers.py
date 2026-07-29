from typing import Protocol, Optional

class NumberReader(Protocol):
    def read(self, img, region) -> Optional[int]: ...

class FixedReader:
    def __init__(self, value):
        self.value = value
    def read(self, img, region):
        return self.value

class TesseractReader:
    """TODO(калибровка): pip install pytesseract + Tesseract в системе.
    Кроп region -> порог -> pytesseract.image_to_string(config='--psm 7 -c
    tessedit_char_whitelist=0123456789'). Возврат int|None."""
    def __init__(self, cfg):
        self.cfg = cfg
    def read(self, img, region):
        raise NotImplementedError("Выбрать/реализовать на калибровке (см. CALIBRATION.md)")

class TemplateReader:
    """TODO(калибровка): эталоны цифр 0-9 из ADB-скринов -> matchTemplate по
    region, сортировка совпадений по x -> склейка в число."""
    def __init__(self, cfg):
        self.cfg = cfg
    def read(self, img, region):
        raise NotImplementedError("Выбрать/реализовать на калибровке (см. CALIBRATION.md)")
