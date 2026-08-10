import re
from config import Config
from src.version import VERSION
from src.gui import GUI_TITLE
from src.engine import BotEngine


def test_config_defaults():
    cfg = Config()
    assert cfg.flask_stop_threshold == 180
    assert cfg.energy_refill_threshold == 20
    assert cfg.farm_levels == frozenset({5})
    assert cfg.mob_squad == 2 and cfg.boss_squad == 1


def test_version_is_major_minor_patch():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_gui_title_contains_version():
    """Заголовок окна собран из VERSION, а не захардкожен — проверяем без
    запуска tkinter (GUI_TITLE строится на импорте модуля)."""
    assert VERSION in GUI_TITLE


def test_engine_start_logs_version():
    """Версия должна попадать в стартовый лог — его присылают человеку."""
    lines = []
    cfg = Config(use_search_strategy=False, strategy="map", dry_run=True)
    eng = BotEngine(driver=None, vision=None, actions=None, cfg=cfg,
                    log=lines.append, sleep=lambda s: None)
    eng.start()
    assert any(VERSION in m for m in lines)
