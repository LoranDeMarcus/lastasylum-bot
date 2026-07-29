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
    squad_slots: dict = field(default_factory=lambda: {1: (0, 0), 2: (0, 0), 3: (0, 0), 4: (0, 0)})
    mob_energy_cost: int = 10
    boss_energy_cost: int = 20

    # --- Экран (ADB-разрешение BlueStacks, проверено screencap) ---
    screen_w: int = 1080
    screen_h: int = 1920

    # --- Регионы чтения чисел (x, y, w, h); плейсхолдеры до калибровки ---
    region_energy: tuple = (0, 0, 0, 0)
    region_deployed: tuple = (0, 0, 0, 0)
    region_flasks: tuple = (0, 0, 0, 0)

    # --- HSV-пороги цветовых масок (low, high); калибруются ---
    mob_hsv_low: tuple = (20, 120, 120)     # жёлтый
    mob_hsv_high: tuple = (35, 255, 255)
    boss_hsv_low: tuple = (5, 120, 120)     # оранжевый
    boss_hsv_high: tuple = (18, 255, 255)
    blob_min_area: int = 200

    # --- Фиксированные координаты кнопок (калибруются; -1 = искать шаблоном) ---
    templates_dir: str = "templates"
    template_match_threshold: float = 0.8
    jitter_px: int = 4
    stop_file: str = "STOP"
