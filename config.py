from dataclasses import dataclass, field

@dataclass
class Config:
    # --- ADB ---
    adb_path: str = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
    adb_serial: str = "emulator-5554"    # BlueStacks_nxt (проверено: adb devices)

    # --- Пороги стратегии ---
    flask_stop_threshold: int = 180      # склянок < 180 -> STOP
    energy_refill_threshold: int = 20    # энергия < 20 -> REFILL
    farm_levels: frozenset = frozenset({5})
    boss_level_threshold: int = 50       # эвристика: level >= -> кандидат в боссы
    mob_squad: int = 2
    boss_squad: int = 1
    squad_slots: dict = field(default_factory=lambda: {1: (200, 1630), 2: (425, 1630), 3: (650, 1630), 4: (875, 1630)})
    mob_energy_cost: int = 10
    boss_energy_cost: int = 20

    # --- Экран (ADB-разрешение BlueStacks, проверено screencap) ---
    screen_w: int = 1080
    screen_h: int = 1920

    # --- Регионы чтения чисел (x, y, w, h); плейсхолдеры до калибровки ---
    region_energy: tuple = (48, 156, 74, 30)     # энергия на HUD карты (слева-вверху)
    region_deployed: tuple = (0, 0, 0, 0)         # TODO: индикатора «Отряд X/4» на карте нет
    region_flasks: tuple = (462, 1543, 105, 50)   # «В наличии: N» у фиолетовой склянки (окно энергии)

    # --- Координаты окна энергии/отправки (фикс., окно с фикс. вёрсткой) ---
    energy_open_xy: tuple = (962, 1802)   # «+» на экране отправки -> открыть окно энергии
    flask_use_xy: tuple = (858, 1540)     # «Использовать» у фиолетовой склянки +50
    energy_close_xy: tuple = (1000, 372)  # крестик закрытия окна энергии

    # --- HSV-маска целей (мобы «5» и боссы «70» — один жёлто-оранжевый тон) ---
    # красные черепа «28» (H≈8) в диапазон НЕ попадают -> сами отсеиваются
    mob_hsv_low: tuple = (14, 120, 120)
    mob_hsv_high: tuple = (28, 255, 255)
    boss_hsv_low: tuple = (5, 120, 120)     # (не используется: боссы того же тона, делим по размеру)
    boss_hsv_high: tuple = (18, 255, 255)
    blob_min_area: int = 1500
    blob_max_area: int = 4200     # моб ~2000, босс (рогатый) ~3100-3500
    # --- Классификация моб/босс по РОГАМ через aspect (зум-инвариантно) ---
    # Плоский череп (моб) aspect≈0.97; рогатый (босс любого ур.) aspect≈1.13.
    boss_aspect_min: float = 1.05     # aspect >= -> босс (рога делают шире-чем-выше)
    target_max_aspect: float = 1.32   # aspect больше -> не череп (повозка ~1.24 и т.п.)
    # HUD-зоны (доли W×H), где детекция игнорируется: верх (аватар/баннер/миникарта),
    # правое меню (территория/альянс), правый-нижний угол (кнопка дома)
    hud_zones: tuple = (
        (0.0, 0.0, 1.0, 0.107),
        (0.755, 0.0, 1.0, 0.271),
        (0.74, 0.885, 1.0, 1.0),
    )

    # --- Состояние отряда: верхний-левый виджет «Отряд» ---
    # Регион метки состояния (x,y,w,h); слова «Перемещение»/«Возвращение...».
    # busy = max(score) > threshold; марш/возврат = argmax; свободен = виджета нет.
    squad_state_region: tuple = (120, 326, 350, 42)
    squad_state_threshold: float = 0.6
    # Слать следующего сразу как «Возвращение» (True) или ждать полного возврата (False)
    send_next_on_return: bool = True

    # --- Фиксированные координаты кнопок (калибруются; -1 = искать шаблоном) ---
    templates_dir: str = "templates"
    template_match_threshold: float = 0.8
    jitter_px: int = 4
    stop_file: str = "STOP"
    # dry-run: движок только логирует решения, НЕ тапает (см. engine)
    dry_run: bool = False
    # verify после тапа по цели: ждать панель «Атака»/«Штурм» столько секунд
    panel_verify_timeout_s: float = 2.5
    # Прогноз боя в превью: «Лёгкая победа»(win) / «Без шансов на победу»(lose).
    # Босса штурмуем только при win (реком. мощь босса может быть >> нашей).
    verdict_threshold: float = 0.7
    # Закрыть превью/панель без отправки: тап по затемнённой области над панелью
    preview_close_xy: tuple = (540, 300)
    # Двухтапный тап по мобу: промах зумит+центрирует цель -> второй тап по
    # центру-спрайту (зум ставит точку тапа в центр экрана; спрайт чуть ниже).
    zoom_center_tap_offset_y: int = 55
