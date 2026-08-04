import random
import subprocess
from typing import Protocol
import numpy as np
import cv2
from src.models import Box

def jitter(x, y, px, rng):
    if px == 0:
        return (x, y)
    return (x + rng.randint(-px, px), y + rng.randint(-px, px))

class Driver(Protocol):
    def screenshot(self): ...
    def tap(self, target): ...
    def swipe(self, x1, y1, x2, y2, dur_ms): ...

class AdbDriver:
    def __init__(self, cfg):
        self.cfg = cfg
        self._rng = random.Random()

    def _adb(self, *args, capture=False):
        cmd = [self.cfg.adb_path, "-s", self.cfg.adb_serial, *args]
        if capture:
            return subprocess.run(cmd, capture_output=True, check=True).stdout
        subprocess.run(cmd, check=True)
        return None

    def screenshot(self):
        png = self._adb("exec-out", "screencap", "-p", capture=True)
        arr = np.frombuffer(png, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("ADB screencap decode failed")
        return img

    def tap(self, target):
        """target: Box (кнопка со своим размером) или кортеж (x, y).

        Пока бьём в центр со старым jitter — человечный разброс по площади
        кнопки появится, когда к драйверу подключат Human (см. план, Task 4)."""
        box = target if isinstance(target, Box) else Box.at(target, self.cfg.tap_size_default)
        jx, jy = jitter(box.x, box.y, self.cfg.jitter_px, self._rng)
        self._adb("shell", "input", "tap", str(jx), str(jy))

    def back(self):
        """Системная «назад» — закрывает случайно открытый диалог/меню.
        Дешёвое восстановление вида, когда флоу не дошёл до панели цели."""
        self._adb("shell", "input", "keyevent", "4")

    def swipe(self, x1, y1, x2, y2, dur_ms=300):
        self._adb("shell", "input", "swipe",
                  str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(dur_ms))

    def zoom_out(self):
        """Отзум щипком (multitouch). Устройство BlueStacks — MT protocol
        type A (ABS_MT_POSITION_X/Y 0..32767, пальцы через SYN_MT_REPORT).
        Два пальца сходятся к центру = уменьшение. Команды подаём в `adb
        shell` через stdin (длинная цепочка не влезает в аргумент adb)."""
        dev = "/dev/input/event4"
        def ev(px, py):
            return round(px * 32767 / self.cfg.screen_w), round(py * 32767 / self.cfg.screen_h)
        lines = []
        def se(t, c, v):
            lines.append(f"sendevent {dev} {t} {c} {v}")
        # GENTLE (один «щелчок» зума): сильный щипок переотзумивает до
        # «пин-зума» (мобы = белые пины). Мягкое сведение sprite -> череп.
        a0, a1 = (540, 600), (540, 830)      # верхний палец вниз (мягко)
        b0, b1 = (540, 1320), (540, 1090)    # нижний палец вверх (мягко)
        steps = 16
        for i in range(steps + 1):
            f = i / steps
            for (p0, p1) in ((a0, a1), (b0, b1)):
                ex, ey = ev(p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f)
                se(3, 53, ex); se(3, 54, ey); se(0, 2, 0)   # X, Y, SYN_MT_REPORT
            se(0, 0, 0)                                       # SYN_REPORT
        se(0, 2, 0); se(0, 0, 0)                             # release
        script = "\n".join(lines) + "\n"
        subprocess.run([self.cfg.adb_path, "-s", self.cfg.adb_serial, "shell"],
                       input=script.encode(), check=True)
