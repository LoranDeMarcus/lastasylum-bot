from config import Config
from src.corruption import CorruptionActions

class FakeDriver:
    """Кадры выдаются по очереди; последний повторяется."""
    def __init__(self, frames):
        self._frames = frames
        self.i = 0
        self.taps = []
        self.backs = 0
    def screenshot(self):
        f = self._frames[min(self.i, len(self._frames) - 1)]
        self.i += 1
        return f
    def tap(self, x, y):
        self.taps.append((x, y))
    def back(self):
        self.backs += 1

class FakeVision:
    def __init__(self, screen_by_frame, buttons_by_frame=None,
                 win_by_frame=None, dialog_frames=()):
        self.screen_by_frame = screen_by_frame
        self.buttons_by_frame = buttons_by_frame or {}
        self.win_by_frame = win_by_frame or {}
        self.dialog_frames = set(dialog_frames)
    def corruption_screen(self, img):
        return self.screen_by_frame.get(img)
    def search_dialog_open(self, img):
        return img in self.dialog_frames
    def find_button(self, img, name):
        return self.buttons_by_frame.get(img, {}).get(name)
    def win_prediction(self, img):
        return self.win_by_frame.get(img)

class FakeActions:
    def __init__(self, flasks=251):
        self.flasks = flasks
        self.refilled = 0
        self.reads = 0
        self.closed = 0
    def refill_energy(self):
        self.refilled += 1
        return self.flasks
    def flasks_left(self):
        self.reads += 1
        return self.flasks
    def close_preview(self):
        self.closed += 1

# Позиция «Штурм» по шаблону намеренно отличается от cfg.corruption_assault_xy,
# иначе «нашли шаблон» и «взяли фикс. координату» неотличимы в ассертах.
ASSAULT_MATCH = (533, 1250)
SEND_MATCH = (548, 1367)

def _happy():
    """Кадры удачного захода. Каждый screenshot() съедает кадр, поэтому
    'panel' и 'preview' повторяются: сначала их видит _wait_screen, затем
    find_button на том же экране."""
    drv = FakeDriver(["dlg", "dlg", "panel", "panel", "preview", "preview"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel", "preview": "preview"},
        buttons_by_frame={
            "panel": {"assault": ASSAULT_MATCH},
            "preview": {"start_assault": SEND_MATCH},
        },
        dialog_frames={"dlg"},
    )
    return drv, vis, FakeActions()

def _run(drv, vis, acts, cfg=None, **kw):
    cfg = cfg or Config()
    c = CorruptionActions(drv, vis, acts, cfg, log=lambda *_: None, sleep=lambda *_: None)
    return c, c.run_once(**kw)

def test_run_once_dispatches_and_taps_full_chain():
    cfg = Config()
    drv, vis, acts = _happy()
    _, res = _run(drv, vis, acts, cfg)
    assert res == "dispatched"
    assert cfg.corruption_search_icon_xy in drv.taps    # лупа
    assert cfg.corruption_tab_xy in drv.taps            # вкладка (безусловно)
    assert cfg.corruption_search_xy in drv.taps         # «Поиск»
    assert ASSAULT_MATCH in drv.taps                    # «Штурм» — по шаблону
    assert cfg.corruption_assault_xy not in drv.taps    # фолбэк не понадобился
    assert SEND_MATCH in drv.taps                       # «Начать Штурм»
    assert drv.backs == 0

def test_run_once_taps_tab_exactly_once_even_when_already_selected():
    # вкладка может быть не выбрана -> тап обязателен всегда, но ровно один
    cfg = Config()
    drv, vis, acts = _happy()
    _run(drv, vis, acts, cfg)
    assert drv.taps.count(cfg.corruption_tab_xy) == 1

def test_run_once_fails_and_backs_when_dialog_missing():
    drv = FakeDriver(["map"])
    vis = FakeVision(screen_by_frame={}, dialog_frames=set())
    _, res = _run(drv, vis, FakeActions())
    assert res == "failed"
    assert drv.backs == 1

def test_run_once_does_not_tap_tab_when_dialog_never_opened():
    # лупа не сработала -> тапать вкладку вслепую по карте нельзя
    cfg = Config()
    drv = FakeDriver(["map"])
    vis = FakeVision(screen_by_frame={}, dialog_frames=set())
    _run(drv, vis, FakeActions(), cfg)
    assert cfg.corruption_tab_xy not in drv.taps

def test_run_once_fails_and_backs_when_search_gives_no_boss():
    drv = FakeDriver(["dlg"])
    vis = FakeVision(screen_by_frame={"dlg": "dialog"}, dialog_frames={"dlg"})
    _, res = _run(drv, vis, FakeActions())
    assert res == "failed"
    assert drv.backs == 1

def test_run_once_fails_when_preview_does_not_open():
    drv = FakeDriver(["dlg", "dlg", "panel"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel"},
        buttons_by_frame={"panel": {"assault": ASSAULT_MATCH}},
        dialog_frames={"dlg"},
    )
    _, res = _run(drv, vis, FakeActions())
    assert res == "failed"
    assert drv.backs == 1

def test_run_once_uses_fixed_coords_when_assault_button_not_matched():
    cfg = Config()
    drv = FakeDriver(["dlg", "dlg", "panel", "panel", "preview", "preview"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel", "preview": "preview"},
        buttons_by_frame={"preview": {"start_assault": SEND_MATCH}},   # assault не найден
        dialog_frames={"dlg"},
    )
    _, res = _run(drv, vis, FakeActions(), cfg)
    assert res == "dispatched"
    assert cfg.corruption_assault_xy in drv.taps
    assert ASSAULT_MATCH not in drv.taps

def test_run_once_refills_from_preview():
    drv, vis, acts = _happy()
    c, res = _run(drv, vis, acts, refill=True)
    assert res == "dispatched"
    assert acts.refilled == 1 and acts.reads == 0
    assert c.last_flasks == 251

def test_run_once_reads_flasks_without_spending():
    drv, vis, acts = _happy()
    c, res = _run(drv, vis, acts, want_flasks=True)
    assert res == "dispatched"
    assert acts.reads == 1 and acts.refilled == 0
    assert c.last_flasks == 251

def test_run_once_does_not_touch_energy_window_by_default():
    drv, vis, acts = _happy()
    c, res = _run(drv, vis, acts)
    assert res == "dispatched"
    assert acts.refilled == 0 and acts.reads == 0
    assert c.last_flasks is None

def test_last_flasks_none_when_energy_window_failed():
    drv, vis, acts = _happy()
    acts.flasks = -1                     # окно энергии не открылось
    c, res = _run(drv, vis, acts, want_flasks=True)
    assert res == "dispatched"
    assert c.last_flasks is None

def test_verdict_gate_off_by_default_dispatches_on_lose():
    drv, vis, acts = _happy()
    vis.win_by_frame = {"preview": "lose"}
    _, res = _run(drv, vis, acts)
    assert res == "dispatched"           # гейт выключен -> вердикт игнорируется

def test_verdict_gate_on_skips_unwinnable():
    cfg = Config()
    cfg.corruption_verdict_gate = True
    drv, vis, acts = _happy()
    vis.win_by_frame = {"preview": "lose"}
    _, res = _run(drv, vis, acts, cfg)
    assert res == "skip_unwinnable"
    assert acts.closed == 1
    assert SEND_MATCH not in drv.taps     # «Начать Штурм» не нажимали

def test_verdict_gate_on_dispatches_on_win():
    cfg = Config()
    cfg.corruption_verdict_gate = True
    drv, vis, acts = _happy()
    vis.win_by_frame = {"preview": "win"}
    _, res = _run(drv, vis, acts, cfg)
    assert res == "dispatched"
    assert acts.closed == 0
