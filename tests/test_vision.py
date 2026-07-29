import numpy as np
import cv2
from config import Config
from src.numbers import FixedReader
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
