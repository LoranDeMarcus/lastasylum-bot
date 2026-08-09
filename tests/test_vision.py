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

# --- Якорь «мы в игре» (HUD энергии) и классификация экрана ---

def test_on_game_view_true_for_game_frames_regardless_of_energy_value():
    """Якорь — иконка молнии, а не цифры: 81 / 50 / 42 на разных кадрах."""
    vis = Vision(Config(), reader=None)
    for name in ("11_corruption_map_idle.png",
                 "19_widget_0of4_energy50.png",
                 "20_map_energy42.png"):
        assert vis.on_game_view(_ref(name)) is True, name

def test_on_game_view_false_under_modal_dialog():
    """Игра блюрит фон под модалкой -> якорь не протекает сквозь чужой экран
    (замер: 0.544 против 0.820 у самого слабого игрового кадра)."""
    vis = Vision(Config(), reader=None)
    assert vis.on_game_view(_ref("21_network_lost_dialog.png")) is False

def test_classify_screen_returns_unknown_for_network_lost_dialog():
    vis = Vision(Config(), reader=None)
    assert vis.classify_screen(_ref("21_network_lost_dialog.png")) == 'unknown'

def test_classify_screen_prefers_topmost_layer():
    """Окно энергии перекрывает превью -> побеждает окно, а не превью."""
    class V(Vision):
        def exit_dialog_open(self, img): return False
        def energy_window_open(self, img): return True
        def corruption_screen(self, img): return 'preview'
    vis = V(Config(), reader=None)
    assert vis.classify_screen("кадр") == 'energy_window'

def test_classify_screen_prefers_base_view_over_game_view():
    """HUD энергии в базе тоже виден (замер 0.911). Если бы game_view
    проверялся раньше, сторож сказал бы «всё в порядке», а движок ударил бы
    по лупе вслепую."""
    vis = Vision(Config(), reader=None)
    assert vis.classify_screen(_ref("29_base_view.png")) == 'base_view'

# --- Якорь экрана базы (кнопка «Мир») ---

def test_on_base_view_true_for_base_frame():
    vis = Vision(Config(), reader=None)
    assert vis.on_base_view(_ref("29_base_view.png")) is True

def test_on_base_view_false_on_world_map():
    """На карте на месте «Мир» кнопка дома — якорь не должен путать их."""
    vis = Vision(Config(), reader=None)
    assert vis.on_base_view(_ref("11_corruption_map_idle.png")) is False

def test_on_base_view_false_on_every_non_base_reference_frame():
    """Замер: база 1.00, все прочие кадры <= 0.27. Тест держит этот разрыв —
    если кто-то уронит порог, он тут же покраснеет.

    Кадры базы называются со словом «base» в имени (например
    `29_base_view.png`, `31_join_icon_base.png`) — на них on_base_view
    законно возвращает True, поэтому такие кадры пропускаем. Любой будущий
    кадр базы достаточно так назвать, чтобы тест не потребовал правки."""
    vis = Vision(Config(), reader=None)
    for name in sorted(os.listdir("reference")):
        if not name.endswith(".png") or "base" in name.lower():
            continue
        img = _ref(name)
        if img is None or img.shape[:2] != (1920, 1080):
            continue          # кропы виджетов, а не полные экраны
        assert vis.on_base_view(img) is False, name

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

def test_energy_window_open_on_refill_window():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.energy_window_open(_ref("27_energy_window_3rows.png")) is True

def test_energy_window_open_false_elsewhere():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.energy_window_open(_ref("26_preview_low_energy.png")) is False
    assert v.energy_window_open(_ref("11_corruption_map_idle.png")) is False

def test_flask_row_y_finds_purple_row():
    """Строк бывает 3 или 4 — координата «Использовать» плавает, поэтому
    строку ищем по иконке фиолетовой склянки."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    y = v.flask_row_y(_ref("27_energy_window_3rows.png"))
    assert y is not None
    assert 1290 <= y <= 1370        # строка фиолетовой склянки на этом кадре

def test_read_flask_stock_after_use():
    """«В наличии: N» открывается, когда счётчик количества исчезает —
    то есть после применения склянок."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    img = _ref("28_energy_window_stock273.png")
    y = v.flask_row_y(img)
    assert v.read_flask_stock(img, y) == 273

def test_read_flask_stock_hidden_behind_quantity_counter():
    """Пока счётчик на месте, он перекрывает число — читать нечего."""
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    img = _ref("27_energy_window_3rows.png")
    y = v.flask_row_y(img)
    assert v.read_flask_stock(img, y) != 273

def test_flask_use_qty_reads_counter():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    img = _ref("27_energy_window_3rows.png")
    y = v.flask_row_y(img)
    assert v.flask_use_qty(img, y) == 2      # при 13/120 влезает 2 склянки

def test_flask_row_found_in_both_window_states():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.flask_row_y(_ref("27_energy_window_3rows.png")) is not None
    assert v.flask_row_y(_ref("28_energy_window_stock273.png")) is not None

def test_flask_row_y_none_without_energy_window():
    cfg = Config()
    v = Vision(cfg, TemplateReader(cfg))
    assert v.flask_row_y(_ref("11_corruption_map_idle.png")) is None
    assert v.flask_row_y(_ref("26_preview_low_energy.png")) is None

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

# --- Box: кнопка со своим размером ---

def test_find_button_returns_box_with_template_size(tmp_path):
    """Размер кнопки уже известен из шаблона — раньше он выбрасывался."""
    tpl = np.zeros((30, 80, 3), np.uint8)
    tpl[5:25, 10:70] = (40, 200, 255)
    cv2.imwrite(str(tmp_path / "btn.png"), tpl)
    img = np.zeros((400, 600, 3), np.uint8)
    img[50:80, 100:180] = tpl
    vis = Vision(Config(templates_dir=str(tmp_path)), reader=None)

    box = vis.find_button(img, "btn")

    assert (box.x, box.y) == (140, 65)      # центр совпадает со старым поведением
    assert (box.w, box.h) == (80, 30)

# --- Присоединение к чужим штурмам: якорь окна «Война альянсов» ---

def test_alliance_war_open_on_window_frame():
    v = Vision(Config(), FixedReader(0))
    assert v.alliance_war_open(_ref("30_alliance_war_empty.png")) is True

def test_alliance_war_open_false_on_map():
    v = Vision(Config(), FixedReader(0))
    assert v.alliance_war_open(_ref("11_corruption_map_idle.png")) is False

def test_classify_screen_knows_join_list():
    v = Vision(Config(), TemplateReader(Config()))
    assert v.classify_screen(_ref("30_alliance_war_empty.png")) == 'join_list'

# --- find_all: все совпадения шаблона, а не только лучшее ---
#
# templates/join_slot.png ещё не нарезан — карточку сбора (Vision.join_cards)
# делает следующая задача, не эта. Для проверки самого механизма find_all
# годится любой уже существующий маленький шаблон — берём energy_close.png
# (кнопка X окна энергии, к режиму join отношения не имеет).

def test_find_all_returns_every_match():
    cfg = Config()
    v = Vision(cfg, FixedReader(0))
    # три копии шаблона на сером фоне
    tpl = cv2.imread(os.path.join(cfg.templates_dir, "energy_close.png"))
    img = np.full((600, 900, 3), 128, dtype=np.uint8)
    th, tw = tpl.shape[:2]
    for x in (100, 300, 500):
        img[200:200 + th, x:x + tw] = tpl
    boxes = v.find_all(img, "energy_close")
    assert len(boxes) == 3
    assert [b.x for b in boxes] == sorted(b.x for b in boxes)   # слева направо

def test_find_all_empty_when_nothing_matches():
    v = Vision(Config(), FixedReader(0))
    img = np.full((600, 900, 3), 128, dtype=np.uint8)
    assert v.find_all(img, "energy_close") == []

# --- Иконка-череп «кто-то набирает помощников» ---
#
# Кадр 31_join_icon_base.png снят на экране БАЗЫ (не карты) — в брифе
# фигурирует имя 31_join_icon_map.png, такого файла в reference/ нет.
#
# Отрицательный кадр 11_corruption_map_idle.png из брифа НЕ подошёл: замер
# по всем reference/*.png (matchTemplate по templates/assault_call.png)
# показал, что иконка на нём тоже видна (0.993) — она осталась от активного
# сбора союзника на момент съёмки этого более раннего калибровочного кадра,
# что подтверждено и глазами (реальный красный череп с бейджем на
# скриншоте). 19_widget_0of4_energy50.png — кадр карты из той же сессии (те
# же 11.2M/10.7M/6.68M в шапке), но снят до появления сбора: иконки на нём
# нет (0.520). Взят как отрицательный пример вместо 11. Подробности замера —
# в CALIBRATION.md.

def test_assault_call_icon_found_on_map_frame():
    v = Vision(Config(), FixedReader(0))
    assert v.assault_call_icon(_ref("31_join_icon_base.png")) is not None

def test_assault_call_icon_absent_without_calls():
    v = Vision(Config(), FixedReader(0))
    assert v.assault_call_icon(_ref("19_widget_0of4_energy50.png")) is None

# --- Кнопка «Обновить» в окне сборов ---

def test_refresh_button_found_when_shown():
    v = Vision(Config(), FixedReader(0))
    assert v.refresh_button(_ref("33_join_refresh.png")) is not None

def test_refresh_button_absent_when_not_shown():
    v = Vision(Config(), FixedReader(0))
    assert v.refresh_button(_ref("32_join_list.png")) is None
