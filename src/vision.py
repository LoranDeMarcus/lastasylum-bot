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

    def _level_below_blob(self, img, blob):
        # Уровень пишется на бирке под иконкой; регион чуть ниже центра блоба.
        x, y, w, h = blob
        region = (x, y + h, w, max(1, h // 2))
        return self.reader.read(img, region)

    def find_targets(self, img):
        targets = []
        for blob in self.find_color_blobs(img, self.cfg.mob_hsv_low,
                                          self.cfg.mob_hsv_high, self.cfg.blob_min_area):
            x, y, w, h = blob
            lvl = self._level_below_blob(img, blob)
            targets.append(Target('mob', lvl if lvl is not None else -1,
                                  x + w // 2, y + h // 2))
        for blob in self.find_color_blobs(img, self.cfg.boss_hsv_low,
                                          self.cfg.boss_hsv_high, self.cfg.blob_min_area):
            x, y, w, h = blob
            lvl = self._level_below_blob(img, blob)
            # kind='boss' если уровень >= порога (эвристика; уточняется шаблоном рогов)
            kind = 'boss' if (lvl is not None and lvl >= self.cfg.boss_level_threshold) else 'mob'
            targets.append(Target(kind, lvl if lvl is not None else -1,
                                  x + w // 2, y + h // 2))
        return targets

    def find_button(self, img, name):
        path = os.path.join(self.cfg.templates_dir, f"{name}.png")
        tpl = cv2.imread(path, cv2.IMREAD_COLOR)
        if tpl is None:
            return None
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if maxv < 0.8:
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
