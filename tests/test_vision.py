import os
import numpy as np
import cv2
import pytest
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

def test_join_screen_preview_on_live_frame():
    v = Vision(Config(), FixedReader(0))
    assert v.join_screen(_ref("34_join_preview.png")) == 'preview'

def test_classify_screen_knows_join_preview():
    v = Vision(Config(), TemplateReader(Config()))
    assert v.classify_screen(_ref("34_join_preview.png")) == 'join_preview'

def test_join_dispatch_template_does_not_fire_on_own_assault_preview():
    """Превью СВОЕГО штурма — не превью присоединения: там кнопка с ценой
    «⚡ 10», её ловит dispatch.png, а join_dispatch.png ловить не должен."""
    v = Vision(Config(), FixedReader(0))
    assert v.find_button(_ref("03_dispatch_preview_squad1.png"), "join_dispatch") is None

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

def test_assault_call_icon_found_on_base_frame():
    """Кадр 31 снят В БАЗЕ: иконка-череп видна и там, поэтому кадр годится
    как позитив, но «на карте» его называть нельзя — тест назывался
    ..._on_map_frame и вводил в заблуждение."""
    v = Vision(Config(), FixedReader(0))
    assert v.assault_call_icon(_ref("31_join_icon_base.png")) is not None

def test_assault_call_icon_found_on_real_map_frame():
    """А это уже настоящая карта мира: бот ищет иконку именно отсюда, и без
    такого позитива про карту не проверялось вообще ничего."""
    v = Vision(Config(), FixedReader(0))
    assert v.assault_call_icon(_ref("20_map_energy42.png")) is not None

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

# --- Карточки сборов: якорь «Элитная скверна», свободные слоты, таймер ---

def test_join_cards_empty_list_frame():
    v = Vision(Config(), TemplateReader(Config()))
    assert v.join_cards(_ref("30_alliance_war_empty.png")) == []

def test_join_cards_reads_live_frame():
    v = Vision(Config(), TemplateReader(Config()))
    cards = v.join_cards(_ref("32_join_list.png"))
    assert cards, "на кадре 32 должна быть хотя бы одна карточка сбора"
    assert all(c.y > 0 for c in cards)
    assert cards == sorted(cards, key=lambda c: c.y)          # сверху вниз
    first = cards[0]
    assert all(a.x <= b.x for a, b in zip(first.slots, first.slots[1:]))
    # Точные ожидания по кадру 32: одна карточка «Ур.30 Элитная скверна»,
    # четыре свободных «+» слева направо, таймер «В команде 00:00:41».
    assert len(cards) == 1
    assert len(first.slots) == 4
    assert [s.x for s in first.slots] == [535, 670, 807, 945]
    assert first.seconds == 41

def test_join_cards_three_card_list_counts_free_slots_and_timers():
    """Кадр 35: три карточки сбора сразу, у ПЕРВОЙ один слот занят аватаром
    соклановца. На кадре 32 свободны были все 4 «+» — баг «занятый слот
    ошибочно посчитан как свободный» такой тест поймать не мог в принципе.
    Заодно это первый живой кадр с несколькими карточками — есть на чём
    проверить сортировку якорей сверху вниз и то, что таймер/слоты не
    перепутались между карточками."""
    v = Vision(Config(), TemplateReader(Config()))
    cards = v.join_cards(_ref("35_join_list_3cards.png"))
    assert len(cards) == 3
    assert cards == sorted(cards, key=lambda c: c.y)          # сверху вниз
    assert [len(c.slots) for c in cards] == [3, 4, 4]
    # у первой карточки занят самый левый «+» (x=535) — его в списке быть не должно
    assert [s.x for s in cards[0].slots] == [670, 807, 945]
    assert [s.x for s in cards[1].slots] == [535, 670, 807, 945]
    assert [s.x for s in cards[2].slots] == [535, 670, 807, 945]
    assert [c.seconds for c in cards] == [26, 41, 45]

def test_join_cards_bounds_slot_search_by_next_card_anchor():
    """Синтетический кадр: два якоря «Элитная скверна» стоят через 300px —
    ближе, чем join_card_height (480). На живых кадрах (32, 35) такого не
    бывает: там карточки стоят ~504-508px, а полоса поиска слотов и так
    упирается в потолок join_card_plus_band[3]=170 что при anchors[i+1], что
    при фолбэке a.y+join_card_height — веткой не различить (см. отчёт
    задачи 4 / CALIBRATION.md). Здесь якоря специально сближены, чтобы
    граница по СЛЕДУЮЩЕМУ якорю оказалась короче фолбэка: между полосой
    поиска первой карточки и самим вторым якорем кладём валидный шаблон
    «+», который обязан остаться СНАРУЖИ обрезанного окна первой карточки
    (иначе он утёк бы в чужую карточку) и который слишком далеко от второй
    карточки, чтобы попасть в её собственную полосу слотов."""
    cfg = Config()
    tpl_card = cv2.imread(os.path.join(cfg.templates_dir, "join_card.png"))
    tpl_slot = cv2.imread(os.path.join(cfg.templates_dir, "join_slot.png"))
    th_c, tw_c = tpl_card.shape[:2]
    th_s, tw_s = tpl_slot.shape[:2]
    img = np.full((900, 1080, 3), 128, dtype=np.uint8)
    img[300:300 + th_c, 100:100 + tw_c] = tpl_card
    img[600:600 + th_c, 100:100 + tw_c] = tpl_card       # якорь через 300px, не 480+
    a_cx, a_cy = 100 + tw_c // 2, 300 + th_c // 2
    dx, dy, bw, bh = cfg.join_card_plus_band
    band_top, band_left = a_cy + dy, a_cx + dx
    # смещение 30 от начала полосы: помещается в фолбэк-окно (170px), но НЕ
    # в реальное окно первой карточки (612 - 476 = 136px < 30 + высота шаблона)
    leak_offset = 30
    leak_x, leak_y = band_left + 50, band_top + leak_offset
    img[leak_y:leak_y + th_s, leak_x:leak_x + tw_s] = tpl_slot

    # Бинарность теста держится на ВЫСОТЕ шаблона «+»: он обязан помещаться в
    # фолбэк-окно и НЕ помещаться в обрезанное. Перережут шаблон крупнее — «+»
    # не влезет никуда и тест продолжит проходить, ничего не различая; мельче
    # — влезет в оба окна и упадёт на ровном месте. Поэтому окно проверяем
    # явно, а не надеемся на него. Сейчас join_slot.png = 122px при окне
    # 107…140px.
    real_h = (600 + th_c // 2) - band_top          # 136: граница по СЛЕДУЮЩЕМУ якорю
    assert real_h - leak_offset < th_s <= bh - leak_offset, (
        f"высота templates/join_slot.png = {th_s}px вышла из окна "
        f"{real_h - leak_offset + 1}…{bh - leak_offset}px — тест перестал "
        f"различать ветку anchors[i+1] и фолбэк a.y+join_card_height; "
        f"пересчитай leak_offset или расстояние между якорями")

    v = Vision(cfg, FixedReader(0))
    cards = v.join_cards(img)
    assert len(cards) == 2
    assert cards[0].slots == []     # «плюс» из зазора не утёк в первую карточку
    assert cards[1].slots == []     # и не попал во вторую (её полоса ниже)

def test_join_cards_sorts_slots_by_x_even_if_match_order_differs():
    """`find_all` сортирует совпадения по (y, x) — то есть по x упорядочивает
    только ВНУТРИ одной строки. На живых кадрах все «+» одной карточки лежат
    на одном y (547 что на кадре 32, что на кадре 35), поэтому там сортировка
    `slots.sort(key=lambda b: b.x)` в `join_cards` ничего не меняет и живым
    кадром не проверяется. Синтетика кладёт два «+» с разным y так, что
    сортировка (y, x) от `find_all` даёт x-убывающий порядок — и только явная
    пересортировка по x в `join_cards` возвращает списко-возрастающий."""
    cfg = Config()
    tpl_card = cv2.imread(os.path.join(cfg.templates_dir, "join_card.png"))
    tpl_slot = cv2.imread(os.path.join(cfg.templates_dir, "join_slot.png"))
    th_c, tw_c = tpl_card.shape[:2]
    th_s, tw_s = tpl_slot.shape[:2]
    img = np.full((900, 1080, 3), 128, dtype=np.uint8)
    img[300:300 + th_c, 100:100 + tw_c] = tpl_card
    a_cx, a_cy = 100 + tw_c // 2, 300 + th_c // 2
    dx, dy, bw, bh = cfg.join_card_plus_band
    band_top, band_left = a_cy + dy, a_cx + dx
    # A: маленький y-офсет, большой x (справа) -> find_all поставит его ПЕРВЫМ
    ax, ay = band_left + 400, band_top + 0
    img[ay:ay + th_s, ax:ax + tw_s] = tpl_slot
    # B: больший y-офсет, маленький x (слева) -> find_all поставит его ВТОРЫМ
    bx, by = band_left + 50, band_top + 40
    img[by:by + th_s, bx:bx + tw_s] = tpl_slot

    v = Vision(cfg, FixedReader(0))
    cards = v.join_cards(img)
    assert len(cards) == 1
    xs = [s.x for s in cards[0].slots]
    assert len(xs) == 2
    assert xs == sorted(xs)          # слева направо, а не в порядке find_all

# --- Режим «Поиск вора»: уровень цели из бейджа под иконкой ---

def _thief_vision():
    cfg = Config()
    return cfg, Vision(cfg, TemplateReader(cfg))

def test_leveled_targets_reads_five_under_skulls():
    """Кадр отзума с ворами: почти у всех целей бейдж читается как 5.

    Не «у всех»: 13 целей, 11 читаются ровно как 5, одна как «51» (склейка
    соседних цифр), у одной бейдж за нижним краем кадра. Нечитаемый бейдж
    безопасен — цель просто пропускается, ложного тапа не будет."""
    cfg, v = _thief_vision()
    img = cv2.imread("reference/40_thief_map_skull.png")
    fives = [t for t in v.leveled_targets(img) if t.level == 5]
    assert len(fives) >= 10

def test_leveled_targets_finds_nothing_readable_on_pin_zoom():
    """Пин-зум: жёлтые блобы есть (повозки), бейджа нет ни у одного.

    Это и делает бейдж доказательством зума, а не только фильтром цели.
    Список целей проверяем непустым отдельно: all() на пустой
    последовательности истинно, и без этой проверки тест продолжил бы
    зеленеть, даже если детекция блобов сломается и вернёт ноль целей —
    перестав доказывать то, ради чего написан."""
    cfg, v = _thief_vision()
    img = cv2.imread("reference/41_thief_map_pin.png")
    targets = v.leveled_targets(img)
    assert len(targets) > 0
    assert all(t.level is None for t in targets)

def test_leveled_targets_reads_boss_levels_too():
    """Уровень берётся из бейджа, а не из kind: у рогатых он свой."""
    cfg, v = _thief_vision()
    img = cv2.imread("reference/01_worldmap_zoomed_out.png")
    levels = {t.level for t in v.leveled_targets(img)}
    assert 5 in levels
    assert levels & {30, 70}

def test_find_targets_behaviour_unchanged():
    """Регрессия: старый find_targets после рефакторинга отдаёт то же."""
    cfg, v = _thief_vision()
    img = cv2.imread("reference/01_worldmap_zoomed_out.png")
    kinds = sorted(t.kind for t in v.find_targets(img))
    assert kinds.count("mob") == 6
    assert kinds.count("boss") == 2

# --- Режим «Поиск вора»: ступени зума и экраны ---

def test_map_zoom_recognises_three_steps():
    """Легенды карты мало: она видна и на скулл-зуме, и на пин-зуме.
    Различает их только бейдж."""
    cfg, v = _thief_vision()
    assert v.map_zoom(cv2.imread("reference/40_thief_map_skull.png")) == "skull"
    assert v.map_zoom(cv2.imread("reference/41_thief_map_pin.png")) == "far"
    assert v.map_zoom(cv2.imread("reference/42_thief_map_close.png")) == "close"

def test_map_zoom_unknown_on_modal():
    cfg, v = _thief_vision()
    assert v.map_zoom(cv2.imread("reference/43_thief_tab.png")) == "unknown"
    # База — не ступень зума карты: легенды карты там нет, но якорь HUD
    # энергии жив (замер 0.911) и без явной проверки map_zoom принял бы её
    # за 'close', а следующий шаг флоу тапнул бы в базе как по кнопке события
    # (event_button там же ложно даёт 0.98-0.99).
    assert v.map_zoom(cv2.imread("reference/29_base_view.png")) == "unknown"
    # Превью отправки — модалка режима, тоже не ступень зума: она не
    # перекрывает легенду и бейджи целиком (замер: 3 из 4 бейджей вокруг
    # неё на этом кадре остаются читаемыми), и без проверки thief_screen
    # map_zoom вернул бы 'skull' чисто по везению раскладки этого кадра —
    # в другой раскладке та же модалка могла бы закрыть все бейджи и
    # соврать 'far'.
    assert v.map_zoom(cv2.imread("reference/45_thief_preview.png")) == "unknown"

def test_map_zoom_skull_without_any_targets_still_reads_skull():
    """Бейдж в этой игре висит под ЛЮБЫМ объектом карты (кристаллы, деревья,
    ресурсные точки), не только под целями. Определение зума не должно
    зависеть от того, есть ли в кадре хоть одна цель — иначе конец волны
    (целей в кадре нет, штатное состояние, ради которого и существует
    «Поиск») на скулл-зуме читался бы как пин-зум, и ensure('skull') после
    удачного «Поиска» вечно щипал бы туда-сюда, ни разу не доехав до
    реальной ступени (см. Important B ревью раунда 1).

    Кадра «скулл-зум без единой цели» в репозитории нет — синтезируем:
    берём настоящий скулл-зум и замазываем ТОЛЬКО иконки целей (даёт
    _target_blobs) фоновым цветом. Бейджи под ними не трогаем — читаются
    ли ИМЕННО они, независимо от икон, и есть суть проверки."""
    cfg, v = _thief_vision()
    img = cv2.imread("reference/40_thief_map_skull.png")
    blobs = v._target_blobs(img)
    assert len(blobs) >= 10          # сцена и правда богата целями до замазки
    bg = (60, 140, 60)               # BGR-зелень: вне HSV обеих масок (цели/бейджи)
    for _kind, cx, cy, w, h in blobs:
        x0, y0 = max(0, cx - w // 2), max(0, cy - h // 2)
        img[y0:y0 + h, x0:x0 + w] = bg
    assert v.leveled_targets(img) == []     # целей действительно не осталось
    assert v.map_zoom(img) == "skull"

def test_thief_tab_open():
    cfg, v = _thief_vision()
    assert v.thief_tab_open(cv2.imread("reference/43_thief_tab.png"))
    assert not v.thief_tab_open(cv2.imread("reference/12_event_dialog_WRONG.png"))
    assert not v.thief_tab_open(cv2.imread("reference/13_corruption_dialog.png"))

def test_thief_panel_on_both_thief_frames():
    """Две панели вора из РАЗНЫХ сессий: порог не подогнан под один кадр."""
    cfg, v = _thief_vision()
    assert v.thief_panel(cv2.imread("reference/44_thief_panel.png"))
    assert v.thief_panel(cv2.imread("reference/02_mob_panel_ataka.png"))
    assert not v.thief_panel(cv2.imread("reference/09_boss_panel_shturm.png"))
    assert not v.thief_panel(cv2.imread("reference/45_thief_preview.png"))

def test_wave_seconds_reads_timer():
    """«00:11:06» -> 666 секунд, а не 1106: цифры склеиваются без двоеточий,
    поэтому разбираем их как ЧЧММСС, а не как одно число."""
    cfg, v = _thief_vision()
    assert v.wave_seconds(cv2.imread("reference/43_thief_tab.png")) == 666

def test_wave_seconds_parses_valid_raw_without_leading_hour_zeros():
    """Синтетика в обход TemplateReader/картинки: FixedReader(1106) — то же
    «00:11:06», что и на живом кадре, но напрямую доказывает разбор ЧЧММСС,
    не завися от региона/детекции цифр. Без позитивного случая рядом с
    негативными тест мусора мог бы выродиться в «всегда None»."""
    cfg = Config()
    v = Vision(cfg, FixedReader(1106))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)   # FixedReader его не читает
    assert v.wave_seconds(blank) == 666

def test_wave_seconds_none_when_raw_exceeds_ceiling():
    """Потолок 995959 («99:59:59») — защита от мусора: значение крупнее
    этого не может быть валидным таймером ни при каком разборе ЧЧММСС.

    Значение 999999 сюда НЕ годится: ЧЧ=99 ММ=99 СС=99 — оно уже отсеется
    проверкой `m > 59`, и тест доказал бы чужую ветку вместо потолка. Взято
    1000006: ЧЧ=100 ММ=00 СС=06 — минуты и секунды валидны, единственное,
    что может его остановить, — сама потолочная проверка `raw > 995959`
    (без неё вернулось бы 100*3600+0*60+6 = 360006)."""
    cfg = Config()
    v = Vision(cfg, FixedReader(1000006))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)
    assert v.wave_seconds(blank) is None

def test_wave_seconds_none_when_minutes_invalid():
    """raw=6106 -> ЧЧ=00, ММ=61, СС=06 — минут «61» не бывает, мусор."""
    cfg = Config()
    v = Vision(cfg, FixedReader(6106))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)
    assert v.wave_seconds(blank) is None

def test_wave_seconds_none_when_seconds_invalid():
    """raw=1161 -> ЧЧ=00, ММ=11, СС=61 — секунд «61» не бывает, мусор."""
    cfg = Config()
    v = Vision(cfg, FixedReader(1161))
    blank = np.full((1920, 1080, 3), 100, dtype=np.uint8)
    assert v.wave_seconds(blank) is None

def test_classify_screen_knows_thief_screens():
    """Без этих классов сторож в боевом режиме глушил бы бота на каждом
    заходе «Поиска»: окно события и панель вора давали 'unknown'."""
    cfg, v = _thief_vision()
    assert v.classify_screen(cv2.imread("reference/43_thief_tab.png")) == "thief_tab"
    assert v.classify_screen(cv2.imread("reference/45_thief_preview.png")) == "thief_preview"

FIXTURES = os.path.join("tests", "fixtures")

def _fixture(name):
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        pytest.skip(f"нет кадра {path} — сними зондом tools/probe_squad_cards.py")
    return cv2.imread(path)

@pytest.mark.parametrize("frame,expected", [
    ("preview_squad_busy.png", "busy"),
    ("preview_squad_returning.png", "returning"),
    ("preview_squad_idle.png", "idle"),
])
def test_preview_squad_state_reads_the_card(frame, expected):
    """Состояние отряда читается ПРЯМО В ПРЕВЬЮ: верхний виджет «Отряд»
    превью перекрывает, а конвейеру нужно знать, освободился ли отряд, не
    выходя из превью."""
    v = Vision(Config(), TemplateReader(Config()))
    assert v.preview_squad_state(_fixture(frame), 2) == expected

def test_preview_squad_state_is_none_off_preview():
    """На карте карточек нет — примитив обязан честно сказать «не знаю»,
    а вызывающий код трактует это как «занят» и лишний раз подождёт."""
    v = Vision(Config(), TemplateReader(Config()))
    blank = np.zeros((1920, 1080, 3), np.uint8)
    assert v.preview_squad_state(blank, 2) is None
