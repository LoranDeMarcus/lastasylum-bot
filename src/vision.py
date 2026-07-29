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
        """Мобы (плоские жёлтые черепа) и боссы (рогатые, того же тона).
        Один жёлто-оранжевый тон ловит и тех и других; разделяем по aspect
        (ш/в): рога делают босса шире-чем-выше (aspect>=boss_aspect_min),
        плоский череп ~квадратный/выше (aspect<...). aspect зум-инвариантен.
        Красные черепа (H≈8) в маску не попадают. HUD-зоны игнорируются.
        Боссы бывают РАЗНОГО уровня — level тут номинальный, реальный тип
        подтверждается панелью («Атака»/«Штурм») после тапа."""
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
            aspect = w / max(1, h)
            if aspect > self.cfg.target_max_aspect:
                continue                       # слишком широкий -> не череп (повозка и т.п.)
            cx, cy = x + w // 2, y + h // 2
            if self._in_hud(cx, cy, W, H):
                continue
            if aspect >= self.cfg.boss_aspect_min:
                targets.append(Target('boss', 0, cx, cy))   # рогатый = босс (ур. неизвестен)
            else:
                targets.append(Target('mob', 5, cx, cy))
        return targets

    def panel_action(self, img):
        """Что за панель открылась после тапа по цели (verify попадания):
        'assault' если видна кнопка «Штурм» (босс), 'attack' если «Атака» (моб),
        иначе None (промах -> вероятно зумнулось). Штурм проверяем первым:
        у босса панель тоже может содержать похожие элементы."""
        if self.find_button(img, "assault") is not None:
            return 'assault'
        if self.find_button(img, "attack") is not None:
            return 'attack'
        return None

    def win_prediction(self, img):
        """Прогноз боя из превью отправки: 'win' («Лёгкая победа») |
        'lose' («Без шансов на победу») | None (не распознан). Ищем шаблоны
        вердиктов по всему кадру (позиция плавает: у моба/босса разная вёрстка).
        Цвет (зелёный/красный) — часть шаблона, помогает различать."""
        win = self._match_full(img, "verdict_win")
        lose = self._match_full(img, "verdict_lose")
        if max(win, lose) < self.cfg.verdict_threshold:
            return None
        return 'win' if win >= lose else 'lose'

    def _match_full(self, img, name):
        tpl = self._state_tpl(name)
        if tpl is None or img.shape[0] < tpl.shape[0] or img.shape[1] < tpl.shape[1]:
            return 0.0
        return float(cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED).max())

    def squad_state(self, img):
        """Состояние отряда по верхнему-левому виджету «Отряд».
        Возвращает 'marching' | 'returning' | 'idle'. Матчим шаблоны слов
        «Перемещение»/«Возвращение...» в фикс. регионе; свободен = виджета
        нет (оба скора низкие). Идентифицирует ЛЮБОЙ активный отряд в виджете
        (для параллельного босс+моб виджет карусельный — это состояние верхней
        видимой карточки)."""
        x, y, w, h = self.cfg.squad_state_region
        crop = img[y:y + h, x:x + w]
        if crop.size == 0:
            return 'idle'
        sm = self._match_state(crop, "state_marching")
        sr = self._match_state(crop, "state_returning")
        best = max(sm, sr)
        if best < self.cfg.squad_state_threshold:
            return 'idle'
        return 'returning' if sr >= sm else 'marching'

    def _match_state(self, crop, name):
        tpl = self._state_tpl(name)
        if tpl is None or crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
            return 0.0
        res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
        return float(res.max())

    def _state_tpl(self, name):
        if not hasattr(self, "_state_cache"):
            self._state_cache = {}
        if name not in self._state_cache:
            path = os.path.join(self.cfg.templates_dir, f"{name}.png")
            self._state_cache[name] = cv2.imread(path, cv2.IMREAD_COLOR)
        return self._state_cache[name]

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
