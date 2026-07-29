import numpy as np
import cv2
from config import Config
from src.numbers import FixedReader
from src.vision import Vision

def _yellow_blob_image():
    img = np.full((400, 400, 3), 128, dtype=np.uint8)  # серый фон (BGR)
    cv2.circle(img, (200, 150), 25, (0, 220, 220), -1)   # жёлтый круг (BGR)
    return img

def test_find_color_blobs_locates_yellow():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    blobs = v.find_color_blobs(_yellow_blob_image(),
                               cfg.mob_hsv_low, cfg.mob_hsv_high, cfg.blob_min_area)
    assert len(blobs) == 1
    x, y, w, h = blobs[0]
    cx, cy = x + w // 2, y + h // 2
    assert abs(cx - 200) <= 5 and abs(cy - 150) <= 5

def test_find_color_blobs_ignores_small_noise():
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    img = np.full((400, 400, 3), 128, dtype=np.uint8)
    cv2.circle(img, (50, 50), 2, (0, 220, 220), -1)      # крошечный шум
    blobs = v.find_color_blobs(img, cfg.mob_hsv_low, cfg.mob_hsv_high, cfg.blob_min_area)
    assert blobs == []

def test_find_targets_classifies_mob(monkeypatch):
    cfg = Config()
    v = Vision(cfg, FixedReader(5))
    targets = v.find_targets(_yellow_blob_image())
    assert any(t.kind == 'mob' and t.level == 5 for t in targets)
