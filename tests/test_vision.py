import os
import numpy as np
import cv2
from config import Config
from src.numbers import FixedReader, TemplateReader
from src.vision import Vision

ORANGE = (0, 180, 255)   # BGR -> HSV H≈21, попадает в маску целей (14..28)

def _blob_image(center, radius, color=ORANGE):
    img = np.full((400, 400, 3), 128, dtype=np.uint8)   # серый фон
    cv2.circle(img, center, radius, color, -1)
    return img

def test_find_color_blobs_locates_target():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    blobs = v.find_color_blobs(_blob_image((200, 200), 25),
                               cfg.mob_hsv_low, cfg.mob_hsv_high, cfg.blob_min_area)
    assert len(blobs) == 1
    x, y, w, h = blobs[0]
    cx, cy = x + w // 2, y + h // 2
    assert abs(cx - 200) <= 5 and abs(cy - 200) <= 5

def test_find_color_blobs_ignores_small_noise():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    img = _blob_image((50, 50), 2)                       # крошечный шум, area << min
    blobs = v.find_color_blobs(img, cfg.mob_hsv_low, cfg.mob_hsv_high, cfg.blob_min_area)
    assert blobs == []

def test_find_targets_classifies_mob():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    # круг ~50px в центре карты -> моб уровня 5
    targets = v.find_targets(_blob_image((200, 200), 25))
    assert [t for t in targets if t.kind == 'mob' and t.level == 5]
    assert not [t for t in targets if t.kind == 'boss']

def test_find_targets_classifies_boss_by_width():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    img = np.full((400, 400, 3), 128, dtype=np.uint8)
    cv2.ellipse(img, (200, 250), (34, 29), 0, 0, 360, ORANGE, -1)  # ~68x58, aspect≈1.17
    bosses = [t for t in v.find_targets(img) if t.kind == 'boss']
    assert len(bosses) == 1

def test_find_targets_ignores_hud_zone():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    # моб-размерный блоб в верхней HUD-полосе (cy≈30 < 0.107*400) -> игнор
    assert v.find_targets(_blob_image((200, 30), 23)) == []

def test_find_targets_rejects_wide_shape():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    img = np.full((400, 400, 3), 128, dtype=np.uint8)
    cv2.ellipse(img, (200, 250), (40, 26), 0, 0, 360, ORANGE, -1)  # ~80x52, aspect≈1.54
    assert v.find_targets(img) == []

def test_squad_state_idle_on_blank():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)  # нет виджета «Отряд»
    assert v.squad_state(blank) == 'idle'

def test_panel_action_none_on_blank():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)  # нет панели
    assert v.panel_action(blank) is None

def test_on_world_map_false_on_blank():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)  # нет легенды карты
    assert v.on_world_map(blank) is False

# --- Режим «Элитная скверна»: счётчик активных отрядов «Отряд N/4» ---

def _ref(name):
    return cv2.imread(os.path.join("reference", name))

def test_active_squads_reads_one_from_widget():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.active_squads(_ref("16_widget_assault_1of4.png")) == 1

def test_active_squads_reads_one_when_widget_shifted():
    # на этом кадре виджет на 22px ниже -> фикс. регион бы промахнулся
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.active_squads(_ref("18_widget_returning_1of4.png")) == 1

def test_active_squads_zero_without_widget():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.active_squads(_ref("11_corruption_map_idle.png")) == 0

def test_active_squads_zero_on_preview():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.active_squads(_ref("15_corruption_preview_all_idle.png")) == 0

def test_active_squads_reads_two():
    """N>=2 — снято живьём при двух отрядах в штурме (карусель из двух строк)."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.active_squads(_ref("24_widget_2of4.png")) == 2

def test_active_squads_reads_explicit_zero_widget():
    """Виджет не всегда исчезает при свободных отрядах — бывает «Отряд 0/4».
    Ноль обязан читаться как ноль, иначе бот решит, что слать некуда."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.active_squads(_ref("19_widget_0of4_energy50.png")) == 0

# --- Чтение энергии (белые цифры поверх зелёной полосы) ---

def test_read_energy_over_partially_filled_bar():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.read_energy(_ref("19_widget_0of4_energy50.png")) == 50

def test_read_energy_various_levels():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.read_energy(_ref("11_corruption_map_idle.png")) == 81
    assert v.read_energy(_ref("16_widget_assault_1of4.png")) == 62
    assert v.read_energy(_ref("20_map_energy42.png")) == 42

def test_read_energy_on_dispatch_preview():
    """На превью энергия своя («52/120» справа-внизу), а HUD карты перекрыт —
    read_energy читает именно HUD, поэтому тут ожидаем None, а не мусор."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.read_energy(_ref("25_corruption_preview_energy52.png")) is None

# --- Режим «Элитная скверна»: распознавание экранов ---

def test_corruption_screen_detects_dialog():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("13_corruption_dialog.png")) == "dialog"

def test_corruption_screen_detects_boss_panel():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("14_corruption_boss_panel.png")) == "boss_panel"

def test_corruption_screen_detects_preview():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("15_corruption_preview_all_idle.png")) == "preview"

def test_corruption_screen_detects_preview_with_busy_squad():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("17_corruption_preview_squad1_busy.png")) == "preview"

def test_corruption_screen_detects_low_energy_preview():
    """При нехватке энергии «Начать Штурм» подменяется на «Увеличить энергию» —
    без этого превью не опознавалось и бот крутил провальные заходы."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("26_preview_low_energy.png")) == "preview_low_energy"

def test_corruption_screen_normal_preview_not_low_energy():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("25_corruption_preview_energy52.png")) == "preview"

def test_corruption_screen_none_on_energy_window():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("27_energy_window_3rows.png")) is None

def test_corruption_screen_none_on_map():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("11_corruption_map_idle.png")) is None

def test_corruption_screen_none_on_wrong_event_dialog():
    # кнопка «Особое событие» открывает ДРУГОЙ диалог — режим не должен его принять
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("12_event_dialog_WRONG.png")) is None

def test_search_dialog_open_true_on_dialog():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.search_dialog_open(_ref("13_corruption_dialog.png")) is True

def test_search_dialog_open_false_on_wrong_event_dialog():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.search_dialog_open(_ref("12_event_dialog_WRONG.png")) is False

def test_search_dialog_open_survives_announcement_banner():
    """Бегущий сверху баннер объявления подкрашивает кнопки строки координат
    и срывает верхний якорь — распознавание держится на кнопке «Поиск»."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.search_dialog_open(_ref("23_corruption_dialog_banner.png")) is True

def test_corruption_screen_dialog_under_banner():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.corruption_screen(_ref("23_corruption_dialog_banner.png")) == "dialog"

def test_search_dialog_open_false_on_map():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.search_dialog_open(_ref("11_corruption_map_idle.png")) is False
    assert v.search_dialog_open(_ref("20_map_energy42.png")) is False

def test_exit_dialog_open_true_on_exit_prompt():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.exit_dialog_open(_ref("22_exit_game_dialog.png")) is True

def test_exit_dialog_open_false_on_map_and_other_dialogs():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.exit_dialog_open(_ref("11_corruption_map_idle.png")) is False
    assert v.exit_dialog_open(_ref("13_corruption_dialog.png")) is False
    assert v.exit_dialog_open(_ref("21_network_lost_dialog.png")) is False
