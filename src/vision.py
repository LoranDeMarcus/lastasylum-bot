import os
import cv2
import numpy as np
from src.models import Target

class Vision:
    def __init__(self, cfg, reader):
        self.cfg = cfg
        self.reader = reader

    def find_color_blobs(self, img, low, high, min_area):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(low, np.uint8), np.array(high, np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs = []
        for c in contours:
            if cv2.contourArea(c) >= min_area:
                blobs.append(tuple(int(v) for v in cv2.boundingRect(c)))
        return blobs

    def _in_hud(self, cx, cy, W, H):
        for x0, y0, x1, y1 in self.cfg.hud_zones:
            if x0 * W <= cx <= x1 * W and y0 * H <= cy <= y1 * H:
                return True
        return False

    def find_targets(self, img):
        """Мобы (жёлтые черепа ур.5) и боссы (рогатые, того же тона но крупнее).
        Один жёлто-оранжевый тон ловит и тех и других; разделяем по ширине блоба.
        Красные черепа (H≈8) в маску не попадают. HUD-зоны игнорируются."""
        H, W = img.shape[:2]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(self.cfg.mob_hsv_low, np.uint8),
                           np.array(self.cfg.mob_hsv_high, np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        targets = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (self.cfg.blob_min_area <= area <= self.cfg.blob_max_area):
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w / max(1, h) > self.cfg.target_max_aspect:
                continue                       # слишком широкий -> не череп (повозка и т.п.)
            cx, cy = x + w // 2, y + h // 2
            if self._in_hud(cx, cy, W, H):
                continue
            if w >= self.cfg.boss_min_w:
                targets.append(Target('boss', 70, cx, cy))
            elif w <= self.cfg.mob_max_w:
                targets.append(Target('mob', 5, cx, cy))
        return targets

    def find_button(self, img, name):
        path = os.path.join(self.cfg.templates_dir, f"{name}.png")
        tpl = cv2.imread(path, cv2.IMREAD_COLOR)
        if tpl is None:
            return None
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if maxv < self.cfg.template_match_threshold:
            return None
        th, tw = tpl.shape[:2]
        return (maxloc[0] + tw // 2, maxloc[1] + th // 2)

    def read_energy(self, img):
        return self.reader.read(img, self.cfg.region_energy)

    def read_deployed(self, img):
        return self.reader.read(img, self.cfg.region_deployed)

    def read_flasks(self, img):
        return self.reader.read(img, self.cfg.region_flasks)

    def squad_slot(self, n):
        return self.cfg.squad_slots[n]
