from config import Config
from src.cancel import Cancel
from src.join import JoinActions
from src.models import Box, JoinCard

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
    def tap(self, target):
        self.taps.append(tuple(target.center) if hasattr(target, "center") else tuple(target))
    def back(self):
        self.backs += 1

class FakeVision:
    def __init__(self, screen_by_frame, cards_by_frame=None, icon=Box(986, 1089, 100, 100),
                 refresh_by_frame=None, buttons_by_frame=None):
        self.screen_by_frame = screen_by_frame
        self.cards_by_frame = cards_by_frame or {}
        self.icon = icon
        self.refresh_by_frame = refresh_by_frame or {}
        self.buttons_by_frame = buttons_by_frame or {}
    def assault_call_icon(self, img):
        return self.icon
    def join_screen(self, img):
        return self.screen_by_frame.get(img)
    def alliance_war_open(self, img):
        return self.screen_by_frame.get(img) == 'list'
    def join_cards(self, img):
        return self.cards_by_frame.get(img, [])
    def refresh_button(self, img):
        return self.refresh_by_frame.get(img)
    def find_button(self, img, name):
        return self.buttons_by_frame.get(img, {}).get(name)
    def exit_dialog_open(self, img):
        return False

def _cfg():
    cfg = Config()
    cfg.human_enabled = False        # без случайных пауз тест детерминирован
    return cfg

def _join(frames, vision, cfg=None):
    cfg = cfg or _cfg()
    return JoinActions(FakeDriver(frames), vision, None, cfg,
                       log=lambda *_: None, sleep=lambda *_: None,
                       cancel=Cancel()), frames

DISPATCH = {'preview': {'dispatch': Box(540, 1360, 300, 90)}}

# Кадры расходуются по одному на КАЖДЫЙ screenshot(). Заход тратит три кадра
# ещё до окна: иконка, подтверждение окна, подтверждение вкладки. Дальше —
# кадр на проверку окна (он же идёт в join_cards), кадр на подтверждение
# превью и кадр на поиск кнопки «Отправиться». Последний кадр в списке
# повторяется, поэтому хвост можно не дублировать.
OPEN = ['list', 'list', 'list']

def test_no_calls_when_icon_absent():
    vision = FakeVision({'a': None})
    vision.icon = None
    actions, _ = _join(['a'], vision)
    assert actions.run_once() == 'no_calls'

def test_joins_rightmost_free_slot():
    card = JoinCard(y=300, slots=[Box(700, 420, 60, 60), Box(900, 420, 60, 60)], seconds=35)
    vision = FakeVision(
        screen_by_frame={'list': 'list', 'preview': 'preview'},
        cards_by_frame={'list': [card]},
        buttons_by_frame=DISPATCH,
    )
    actions, _ = _join(OPEN + ['list', 'preview'], vision)
    assert actions.run_once() == 'dispatched'
    assert (900, 420) in actions.driver.taps          # тапнули ПРАВЫЙ крестик
    assert (700, 420) not in actions.driver.taps

def test_skips_card_with_expiring_timer():
    hot = JoinCard(y=300, slots=[Box(900, 420, 60, 60)], seconds=4)
    ok = JoinCard(y=800, slots=[Box(900, 920, 60, 60)], seconds=40)
    vision = FakeVision(
        screen_by_frame={'list': 'list', 'preview': 'preview'},
        cards_by_frame={'list': [hot, ok]},
        buttons_by_frame=DISPATCH,
    )
    actions, _ = _join(OPEN + ['list', 'preview'], vision)
    assert actions.run_once() == 'dispatched'
    assert (900, 920) in actions.driver.taps
    assert (900, 420) not in actions.driver.taps

def test_unreadable_timer_does_not_block_join():
    card = JoinCard(y=300, slots=[Box(900, 420, 60, 60)], seconds=None)
    vision = FakeVision(
        screen_by_frame={'list': 'list', 'preview': 'preview'},
        cards_by_frame={'list': [card]},
        buttons_by_frame=DISPATCH,
    )
    actions, _ = _join(OPEN + ['list', 'preview'], vision)
    assert actions.run_once() == 'dispatched'

def test_full_card_is_skipped():
    full = JoinCard(y=300, slots=[], seconds=40)
    ok = JoinCard(y=800, slots=[Box(900, 920, 60, 60)], seconds=40)
    vision = FakeVision(
        screen_by_frame={'list': 'list', 'preview': 'preview'},
        cards_by_frame={'list': [full, ok]},
        buttons_by_frame=DISPATCH,
    )
    actions, _ = _join(OPEN + ['list', 'preview'], vision)
    assert actions.run_once() == 'dispatched'
    assert (900, 920) in actions.driver.taps

def test_lost_window_returns_without_extra_taps():
    vision = FakeVision(screen_by_frame={'list': 'list', 'gone': None})
    actions, _ = _join(OPEN + ['gone'], vision)
    assert actions.run_once() == 'lost_window'
    assert actions.driver.backs == 0        # окно пропало само — BACK не нужен

def test_race_for_slot_retries_next_card():
    """Остались в списке после тапа по «+» — места разобрали. Это не провал:
    пробуем следующую карточку."""
    taken = JoinCard(y=300, slots=[Box(900, 420, 60, 60)], seconds=40)
    ok = JoinCard(y=800, slots=[Box(900, 920, 60, 60)], seconds=40)
    vision = FakeVision(
        screen_by_frame={'list': 'list', 'second': 'list', 'preview': 'preview'},
        cards_by_frame={'list': [taken, ok], 'second': [ok]},
        buttons_by_frame=DISPATCH,
    )
    actions, _ = _join(OPEN + ['list', 'list', 'second', 'preview'], vision)
    assert actions.run_once() == 'dispatched'
    assert (900, 420) in actions.driver.taps      # первый тап — по разобранному
    assert (900, 920) in actions.driver.taps      # второй — по живому слоту

def test_taps_refresh_when_it_appears():
    fresh = JoinCard(y=300, slots=[Box(900, 420, 60, 60)], seconds=30)
    vision = FakeVision(
        screen_by_frame={'list': 'list', 'fresh': 'list', 'preview': 'preview'},
        cards_by_frame={'list': [], 'fresh': [fresh]},
        refresh_by_frame={'list': Box(548, 1800, 300, 90)},
        buttons_by_frame=DISPATCH,
    )
    actions, _ = _join(OPEN + ['list', 'fresh', 'preview'], vision)
    assert actions.run_once() == 'dispatched'
    assert (548, 1800) in actions.driver.taps         # «Обновить» нажата
