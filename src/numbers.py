import os
import glob
from typing import Protocol, Optional
import cv2
import numpy as np

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
    """Читает целое число из региона по эталонам цифр 0-9.

    Пайплайн: кроп region -> grayscale -> Otsu-бинаризация с авто-инверсией
    (цифры всегда белые на чёрном) -> поиск компонент (цифр) -> сортировка по x
    -> каждая цифра нормализуется по высоте и сопоставляется с эталонами
    (matchTemplate TM_CCOEFF_NORMED) -> склейка в число.

    Эталоны берутся из `<templates_dir>/digits/<d>.png` (0-9). Устойчив к
    масштабу (нормализация высоты) и к цвету текста (авто-инверсия)."""

    def __init__(self, cfg, norm_h: int = 28, min_match: float = 0.33):
        self.cfg = cfg
        self.norm_h = norm_h
        self.min_match = min_match
        self._templates = None

    def _binarize(self, gray):
        _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if b.mean() > 127:          # цифры должны быть меньшинством (белые на чёрном)
            b = cv2.bitwise_not(b)
        return b

    def _norm_glyph(self, bin_glyph):
        ys, xs = np.where(bin_glyph > 0)
        if len(xs) == 0:
            return None
        g = bin_glyph[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        w = max(1, int(round(g.shape[1] * self.norm_h / g.shape[0])))
        return cv2.resize(g, (w, self.norm_h), interpolation=cv2.INTER_NEAREST)

    def _load_templates(self):
        """Для каждой цифры грузим все варианты: `<d>.png` и `<d>_*.png`
        (разные шрифты: жирный HUD, тонкий панельный). Матчинг — по лучшему
        варианту. Эталоны сохранены как «белое-на-чёрном» (без авто-инверсии)."""
        d = os.path.join(self.cfg.templates_dir, "digits")
        tpl = {}
        for n in range(10):
            variants = []
            paths = glob.glob(os.path.join(d, f"{n}.png")) + \
                    glob.glob(os.path.join(d, f"{n}_*.png"))
            for path in sorted(paths):
                im = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if im is None:
                    continue
                _, bt = cv2.threshold(im, 127, 255, cv2.THRESH_BINARY)
                g = self._norm_glyph(bt)
                if g is not None:
                    variants.append(g)
            if variants:
                tpl[n] = variants
        return tpl

    def _match(self, glyph, tpl):
        # приводим к одной ширине для честного сравнения
        w = max(glyph.shape[1], tpl.shape[1])
        a = cv2.resize(glyph, (w, self.norm_h), interpolation=cv2.INTER_NEAREST).astype(np.float32)
        b = cv2.resize(tpl, (w, self.norm_h), interpolation=cv2.INTER_NEAREST).astype(np.float32)
        res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
        return float(res.max())

    def read(self, img, region):
        x, y, w, h = region
        if w <= 0 or h <= 0:
            return None
        crop = img[y:y + h, x:x + w]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        b = self._binarize(gray)
        contours, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(c) for c in contours]
        boxes = [bb for bb in boxes if bb[3] >= 0.4 * h and bb[2] >= 2]
        boxes.sort(key=lambda bb: bb[0])
        if not boxes:
            return None
        if self._templates is None:
            self._templates = self._load_templates()
        if not self._templates:
            return None
        digits = []
        for (bx, by, bw, bh) in boxes:
            g = self._norm_glyph(b[by:by + bh, bx:bx + bw])
            if g is None:
                continue
            best_n, best = None, -1.0
            for n, variants in self._templates.items():
                s = max(self._match(g, v) for v in variants)
                if s > best:
                    best, best_n = s, n
            if best_n is not None and best >= self.min_match:
                digits.append(str(best_n))
        if not digits:
            return None
        try:
            return int("".join(digits))
        except ValueError:
            return None
