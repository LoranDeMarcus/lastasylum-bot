import random
import subprocess
from typing import Protocol
import numpy as np
import cv2

def jitter(x, y, px, rng):
    if px == 0:
        return (x, y)
    return (x + rng.randint(-px, px), y + rng.randint(-px, px))

class Driver(Protocol):
    def screenshot(self): ...
    def tap(self, x, y): ...
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

    def tap(self, x, y):
        jx, jy = jitter(int(x), int(y), self.cfg.jitter_px, self._rng)
        self._adb("shell", "input", "tap", str(jx), str(jy))

    def swipe(self, x1, y1, x2, y2, dur_ms=300):
        self._adb("shell", "input", "swipe",
                  str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(dur_ms))
