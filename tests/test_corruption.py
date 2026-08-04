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
                 win_by_frame=None, dialog_frames=(), exit_frames=(),
                 energy_frames=(), flask_row=1328, flask_qty=2):
        self.screen_by_frame = screen_by_frame
        self.buttons_by_frame = buttons_by_frame or {}
        self.win_by_frame = win_by_frame or {}
        self.dialog_frames = set(dialog_frames)
        self.exit_frames = set(exit_frames)
        self.energy_frames = set(energy_frames)
        self.flask_row = flask_row
        self.flask_qty = flask_qty
    def energy_window_open(self, img):
        return img in self.energy_frames
    def flask_row_y(self, img):
        return self.flask_row
    def flask_use_qty(self, img, row_y):
        return self.flask_qty
    def corruption_screen(self, img):
        return self.screen_by_frame.get(img)
    def search_dialog_open(self, img):
        return img in self.dialog_frames
    def exit_dialog_open(self, img):
        return img in self.exit_frames
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

def _low_energy_then_refill():
    """Превью с «Увеличить энергию» -> окно энергии -> склянка -> превью."""
    drv = FakeDriver(["dlg", "dlg", "panel", "panel", "lowe",
                      "energy", "energy", "preview", "preview"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel",
                         "lowe": "preview_low_energy", "preview": "preview"},
        buttons_by_frame={
            "panel": {"assault": ASSAULT_MATCH},
            "preview": {"start_assault": SEND_MATCH},
        },
        dialog_frames={"dlg"},
        energy_frames={"energy"},
    )
    return drv, vis, FakeActions()

def test_refill_uses_purple_flask_row_not_fixed_coord():
    """Строк в окне 3 или 4 — Y кнопки «Использовать» берём от найденной
    строки фиолетовой склянки."""
    cfg = Config()
    drv, vis, acts = _low_energy_then_refill()
    vis.flask_row = 1540                 # вёрстка с четырьмя строками
    c, res = _run(drv, vis, acts, cfg, refill=True)
    assert res == "dispatched"
    assert (cfg.flask_use_x, 1540) in drv.taps
    assert c.flasks_used == 2            # счётчик количества показал 2

def test_refill_counts_actual_quantity_used():
    drv, vis, acts = _low_energy_then_refill()
    vis.flask_qty = 3
    c, _ = _run(drv, vis, acts, refill=True)
    assert c.flasks_used == 3

def test_refill_skipped_when_not_allowed():
    cfg = Config()
    drv, vis, acts = _low_energy_then_refill()
    c, res = _run(drv, vis, acts, cfg, refill=False)
    assert res == "low_energy"
    assert c.flasks_used == 0
    assert cfg.corruption_boost_energy_xy not in drv.taps
    assert acts.closed == 1

def test_refill_does_not_spend_when_quantity_unreadable():
    """Не прочитали, сколько уйдёт -> не тратим вслепую, учёт остался бы кривым."""
    drv, vis, acts = _low_energy_then_refill()
    vis.flask_qty = None
    c, res = _run(drv, vis, acts, refill=True)
    assert res == "low_energy"
    assert c.flasks_used == 0

def test_refill_does_not_spend_when_purple_row_not_found():
    drv, vis, acts = _low_energy_then_refill()
    vis.flask_row = None
    c, res = _run(drv, vis, acts, refill=True)
    assert res == "low_energy"
    assert c.flasks_used == 0

def test_refill_aborts_when_energy_window_did_not_open():
    drv = FakeDriver(["dlg", "dlg", "panel", "panel", "lowe", "lowe"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel",
                         "lowe": "preview_low_energy"},
        buttons_by_frame={"panel": {"assault": ASSAULT_MATCH}},
        dialog_frames={"dlg"},
        energy_frames=set(),
    )
    c, res = _run(drv, vis, FakeActions(), refill=True)
    assert res == "low_energy"
    assert c.flasks_used == 0

def test_run_once_does_not_touch_energy_window_by_default():
    drv, vis, acts = _happy()
    c, res = _run(drv, vis, acts)
    assert res == "dispatched"
    assert c.flasks_used == 0

def test_run_once_reports_low_energy_and_closes_preview():
    """Энергии меньше стоимости -> игра подменяет «Начать Штурм» на «Увеличить
    энергию». Выходим чисто, без тапов по окну энергии."""
    drv = FakeDriver(["dlg", "dlg", "panel", "panel", "lowe"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel",
                         "lowe": "preview_low_energy"},
        buttons_by_frame={"panel": {"assault": ASSAULT_MATCH}},
        dialog_frames={"dlg"},
    )
    acts = FakeActions()
    _, res = _run(drv, vis, acts)
    assert res == "low_energy"
    assert acts.closed == 1                  # превью закрыто
    assert acts.refilled == 0 and acts.reads == 0
    assert SEND_MATCH not in drv.taps
    assert drv.backs == 0                    # BACK не нужен, вышли штатно

def test_run_once_aborts_if_preview_gone_after_flask():
    """Окно энергии не закрылось -> «Начать Штурм» недоступен: отменяем заход,
    а не тапаем вслепую по чужому окну."""
    drv = FakeDriver(["dlg", "dlg", "panel", "panel", "lowe",
                      "energy", "energy", "energy"])
    vis = FakeVision(
        screen_by_frame={"dlg": "dialog", "panel": "boss_panel",
                         "lowe": "preview_low_energy"},
        buttons_by_frame={"panel": {"assault": ASSAULT_MATCH}},
        dialog_frames={"dlg"},
        energy_frames={"energy"},
    )
    c, res = _run(drv, vis, FakeActions(), refill=True)
    assert res == "failed"
    assert drv.backs == 1               # вышли через BACK, а не тапом по окну
    assert c.flasks_used == 2           # склянка потрачена, но отправки не было

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

def test_abort_cancels_exit_game_dialog_opened_by_back():
    """«Назад» на чистой карте открывает «Выйти из игры?» — бот обязан нажать
    «Отмена», иначе следующий слепой тап может закрыть игру."""
    cfg = Config()
    drv = FakeDriver(["map", "exit"])
    vis = FakeVision(
        screen_by_frame={},
        buttons_by_frame={"exit": {"exit_cancel": (297, 1030)}},
        dialog_frames=set(),
        exit_frames={"exit"},
    )
    _, res = _run(drv, vis, FakeActions(), cfg)
    assert res == "failed"
    assert drv.backs == 1
    assert (297, 1030) in drv.taps            # «Отмена» нажата

def test_abort_does_not_tap_when_no_exit_dialog():
    cfg = Config()
    drv = FakeDriver(["map", "map"])
    vis = FakeVision(screen_by_frame={}, dialog_frames=set(), exit_frames=set())
    _, res = _run(drv, vis, FakeActions(), cfg)
    assert res == "failed"
    assert cfg.exit_cancel_xy not in drv.taps

def test_verdict_gate_on_dispatches_on_win():
    cfg = Config()
    cfg.corruption_verdict_gate = True
    drv, vis, acts = _happy()
    vis.win_by_frame = {"preview": "win"}
    _, res = _run(drv, vis, acts, cfg)
    assert res == "dispatched"
    assert acts.closed == 0
