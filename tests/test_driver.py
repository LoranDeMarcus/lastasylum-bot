import random
import subprocess
import cv2
import numpy as np
import pytest
from config import Config
from src.driver import jitter, AdbDriver, strip_adb_banner
from src.models import Box
from src.human import Human

# Ровно то, что adb 1.0.36 (BlueStacks HD-Adb.exe) пишет в stdout, когда
# демон ещё не поднят. Проверено вживую: kill-server -> exec-out screencap.
DAEMON_BANNER = (b"* daemon not running. starting it now on port 5037 *\n"
                 b"* daemon started successfully *\n")

def _png_bytes(w=8, h=4):
    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    return buf.tobytes()

def test_screenshot_survives_adb_daemon_banner():
    """Регрессия падения бота: adb 1.0.36 печатает баннер запуска демона в
    stdout, а не в stderr, и он приклеивается ПЕРЕД PNG первого кадра.
    imdecode такого не понимал -> RuntimeError на первой же итерации."""
    drv = AdbDriver(Config())
    drv._adb = lambda *a, **k: DAEMON_BANNER + _png_bytes()
    img = drv.screenshot()
    assert img.shape == (4, 8, 3)

def test_strip_banner_leaves_clean_png_untouched():
    png = _png_bytes()
    assert strip_adb_banner(png) == png

def test_screenshot_error_tells_what_came_back():
    """Голое «decode failed» не даёт понять, что случилось. В сообщении
    должен быть размер и начало ответа, иначе разбор снова начнётся с нуля."""
    drv = AdbDriver(Config())
    drv._adb = lambda *a, **k: b"error: device offline"
    with pytest.raises(RuntimeError, match="device offline"):
        drv.screenshot()

def test_screenshot_reports_empty_output():
    """Пустой stdout при коде возврата 0: adb 1.0.36 не пробрасывает код
    удалённой команды, так что упавший screencap выглядит как успех."""
    drv = AdbDriver(Config())
    drv._adb = lambda *a, **k: b""
    with pytest.raises(RuntimeError, match="0 байт"):
        drv.screenshot()

def test_adb_starts_daemon_before_first_command(monkeypatch):
    """Демон поднимается отдельной командой, чей stdout никому не нужен —
    тогда баннеру неоткуда попасть в бинарный кадр. Один раз на процесс."""
    cmds = []
    def fake_run(cmd, **kw):
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    drv = AdbDriver(Config())
    drv.back()
    drv.back()
    assert cmds[0][1] == "start-server"
    assert sum(1 for c in cmds if "start-server" in c) == 1
    assert cmds[1][-1] == "4" and cmds[2][-1] == "4"

def test_back_sends_keyevent_back():
    """BACK закрывает случайно открытый диалог -> вид снова чистый."""
    drv = AdbDriver(Config())
    calls = []
    drv._adb = lambda *a, **k: calls.append(a)
    drv.back()
    assert calls == [("shell", "input", "keyevent", "4")]

def test_jitter_within_bounds():
    rng = random.Random(42)
    for _ in range(100):
        x, y = jitter(500, 800, px=4, rng=rng)
        assert 496 <= x <= 504
        assert 796 <= y <= 804

def test_jitter_zero_px_is_identity():
    rng = random.Random(0)
    assert jitter(10, 20, px=0, rng=rng) == (10, 20)

def test_tap_accepts_box_and_tuple():
    """tap принимает и Box, и голый кортеж — вторые остаются у tools/*."""
    drv = AdbDriver(Config(jitter_px=0))
    calls = []
    drv._adb = lambda *a, **k: calls.append(a)

    drv.tap(Box(500, 800, 200, 60))
    drv.tap((10, 20))

    assert calls == [("shell", "input", "tap", "500", "800"),
                     ("shell", "input", "tap", "10", "20")]

def test_tap_box_uses_named_size_and_falls_back_to_default():
    cfg = Config()
    known = cfg.tap_box("corruption_search", (548, 1785))
    unknown = cfg.tap_box("такой_кнопки_нет", (100, 200))

    assert known.center == (548, 1785)
    assert (known.w, known.h) == cfg.tap_sizes["corruption_search"]
    assert (unknown.w, unknown.h) == cfg.tap_size_default

def _drv_with_human(cfg, seed=5):
    drv = AdbDriver(cfg, human=Human(cfg, rng=random.Random(seed)))
    calls = []
    drv._adb = lambda *a, **k: calls.append(a)
    return drv, calls

def test_taps_spread_inside_button_when_human_attached():
    cfg = Config()
    drv, calls = _drv_with_human(cfg)
    box = Box(548, 1785, 300, 88)
    for _ in range(50):
        drv.tap(box)
    xs = {int(c[3]) for c in calls}
    assert len(xs) > 5                                  # не одна выверенная точка
    assert all(473 <= int(c[3]) <= 623 for c in calls)  # внутри центральных 50%
    assert all(1763 <= int(c[4]) <= 1807 for c in calls)

def test_human_disabled_falls_back_to_center():
    cfg = Config(human_enabled=False, jitter_px=0)
    drv, calls = _drv_with_human(cfg)
    drv.tap(Box(100, 200, 300, 88))
    assert calls == [("shell", "input", "tap", "100", "200")]

def test_variable_hold_uses_swipe_with_equal_coords():
    """input tap даёт нулевую длительность нажатия — машинный признак.
    Переменное нажатие делается swipe'ом в ту же точку."""
    cfg = Config(human_tap_hold=True, tap_inset=0.0)
    drv, calls = _drv_with_human(cfg)
    drv.tap(Box(500, 800, 200, 60))
    cmd = calls[0]
    assert cmd[:2] == ("shell", "input") and cmd[2] == "swipe"
    assert cmd[3:5] == ("500", "800") and cmd[5:7] == ("500", "800")
    assert cfg.tap_hold_ms[0] <= int(cmd[7]) <= cfg.tap_hold_ms[1]

def test_human_disabled_overrides_hold_flag():
    """При human_enabled=False старое поведение соблюдается точно,
    даже если human_tap_hold=True и Human передан. Иначе нарушается
    гарантия совместимости."""
    cfg = Config(human_enabled=False, human_tap_hold=True, jitter_px=0)
    drv, calls = _drv_with_human(cfg)
    drv.tap(Box(500, 800, 200, 60))
    cmd = calls[0]
    # Обязано быть input tap, а не swipe, несмотря на human_tap_hold=True
    assert cmd == ("shell", "input", "tap", "500", "800")
