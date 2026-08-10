import random
import subprocess
from typing import Protocol
import numpy as np
import cv2
from src.models import Box

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

def jitter(x, y, px, rng):
    if px == 0:
        return (x, y)
    return (x + rng.randint(-px, px), y + rng.randint(-px, px))

def strip_adb_banner(out):
    """Отрезать служебный текст adb перед PNG.

    adb 1.0.36 (он же BlueStacks HD-Adb.exe) печатает «* daemon not running.
    starting it now on port 5037 *» в stdout, а не в stderr. Если демон не
    поднят, этот баннер приклеивается ПЕРЕД кадром `exec-out screencap` — и
    картинка перестаёт декодироваться. Сервер мы теперь поднимаем заранее
    (_ensure_server), но он может умереть и посреди работы (перезапуск
    BlueStacks, чужой adb на порту 5037), поэтому кадр чистим всегда."""
    i = out.find(PNG_MAGIC)
    return out if i <= 0 else out[i:]      # -1 (нет PNG) отдаём как есть: пусть падает с диагностикой

class Driver(Protocol):
    def screenshot(self): ...
    def tap(self, target): ...
    def swipe(self, x1, y1, x2, y2, dur_ms): ...

class AdbDriver:
    def __init__(self, cfg, human=None):
        self.cfg = cfg
        self.human = human
        self._rng = random.Random()
        self._server_ready = False
        self.last_stderr = b""

    def _ensure_server(self):
        """Поднять adb-демона отдельной командой, до первого кадра.

        Иначе баннер запуска демона уходит в stdout первой же команды и
        ломает PNG (см. strip_adb_banner). Здесь stdout выбрасываем, так
        что баннеру некуда попасть. check=False: если демон не поднялся,
        настоящая команда упадёт следом с внятной ошибкой."""
        if self._server_ready:
            return
        subprocess.run([self.cfg.adb_path, "start-server"],
                       capture_output=True, check=False)
        self._server_ready = True

    def _adb(self, *args, capture=False):
        self._ensure_server()
        cmd = [self.cfg.adb_path, "-s", self.cfg.adb_serial, *args]
        if capture:
            res = subprocess.run(cmd, capture_output=True, check=True)
            self.last_stderr = res.stderr      # для диагностики битого кадра
            return res.stdout
        subprocess.run(cmd, check=True)
        return None

    def screenshot(self):
        raw = self._adb("exec-out", "screencap", "-p", capture=True)
        png = strip_adb_banner(raw)
        arr = np.frombuffer(png, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
        if img is None:
            # Без содержимого ответа причину не отличить: пустой stdout —
            # это упавший на устройстве screencap (adb 1.0.36 не пробрасывает
            # его код возврата), мусор в начале — служебный текст adb.
            raise RuntimeError(
                f"ADB screencap decode failed: получено {len(raw)} байт, "
                f"начало {raw[:80]!r}"
                + (f", stderr: {self.last_stderr[:200]!r}" if self.last_stderr else ""))
        return img

    def tap(self, target):
        """target: Box (кнопка со своим размером) или кортеж (x, y).

        С Human тап приходит в случайную точку ВНУТРИ кнопки: одна и та же
        выверенная координата — машинный признак. Без Human — старое
        поведение (центр + jitter), чтобы tools/*.py работали без правок."""
        box = target if isinstance(target, Box) else Box.at(target, self.cfg.tap_size_default)
        if self.human is not None and self.cfg.human_enabled:
            x, y = self.human.point_in(box)
        else:
            x, y = jitter(box.x, box.y, self.cfg.jitter_px, self._rng)
        if self.human is not None and self.cfg.human_enabled and self.cfg.human_tap_hold:
            # input tap = down/up с нулевой длительностью. Нажатие переменной
            # длины делается swipe'ом в ту же точку. Флаг выключен по
            # умолчанию: это другой тип события, игра МОЖЕТ отработать его
            # как долгое нажатие — включать после живой проверки.
            ms = self.human.hold_ms()
            self._adb("shell", "input", "swipe", str(x), str(y), str(x), str(y), str(ms))
        else:
            self._adb("shell", "input", "tap", str(x), str(y))

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
        self._ensure_server()          # команда идёт мимо _adb — демона поднимаем сами
        subprocess.run([self.cfg.adb_path, "-s", self.cfg.adb_serial, "shell"],
                       input=script.encode(), check=True)
