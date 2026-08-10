import os
import cv2
import numpy as np
from src.models import Target, Box, JoinCard

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

    def energy_window_open(self, img):
        """Открыто ли окно «Восстановить энергию» (по заголовку)."""
        return self.find_button(img, "energy_window_title") is not None

    def flask_row_y(self, img):
        """Вертикальный центр строки с ФИОЛЕТОВОЙ склянкой +50 в окне энергии,
        или None если её не видно.

        Строк бывает 3 или 4: при четырёх третьей идёт зелёная склянка +10 и
        всё ниже съезжает, поэтому фиксированная координата «Использовать»
        промахивается. Фиолетовая всегда ПОСЛЕДНЯЯ строка — из всех совпадений
        берём самое нижнее."""
        tpl = self._state_tpl("flask_purple")
        if tpl is None or img.shape[0] < tpl.shape[0] or img.shape[1] < tpl.shape[1]:
            return None
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        ys, _ = np.where(res >= self.cfg.template_match_threshold)
        if len(ys) == 0:
            return None
        return int(ys.max() + tpl.shape[0] // 2)

    def flask_use_qty(self, img, row_y):
        """Сколько склянок ещё ВЛЕЗЕТ по энергии — число в счётчике этой строки
        (проверено: при 8/120 стояло 2). None, если счётчика нет.

        Один тап «Использовать» тратит ровно ОДНУ склянку (+50), так что это
        число — верхний предел числа тапов, а не расход за тап."""
        x, dy, w, h = self.cfg.flask_qty_region_rel
        return self.reader.read(img, (x, row_y + dy, w, h),
                                white_threshold=self.cfg.energy_white_threshold)

    def read_flask_stock(self, img, row_y):
        """Остаток склянок «В наличии: N» в строке фиолетовой склянки.

        Виден ТОЛЬКО когда счётчик количества исчез — то есть когда долить
        осталось меньше 50 энергии (обычно уже ПОСЛЕ применения склянок).
        Пока счётчик на месте, он перекрывает это число и вернётся None."""
        x, dy, w, h = self.cfg.flask_stock_region_rel
        return self.reader.read(img, (x, row_y + dy, w, h))

    def exit_dialog_open(self, img):
        """Открыт ли диалог «Выйти из игры?». Он появляется от системной
        «назад» на чистой карте — то есть ровно на пути восстановления бота
        после неудавшегося шага. Пропустить его нельзя: следующий слепой тап
        может подтвердить выход."""
        return self.find_button(img, "exit_cancel") is not None

    def search_dialog_open(self, img):
        """Открыт ли диалог поиска (тот, что по лупе) — на ЛЮБОЙ его вкладке.

        Два независимых признака, потому что ни один не покрывает всё:
        - кнопка «Поиск» внизу: есть только на вкладке скверны, зато её не
          задевают бегущие сверху баннеры объявлений;
        - кнопки лупы/звезды в строке координат «X: … Y: …»: видны на любой
          вкладке, но полупрозрачный баннер их подкрашивает и матч срывается
          (замер: 1.00 без баннера, 0.61 с баннером).
        Метка активной вкладки как якорь не годится вовсе: неактивная вкладка
        темнее и не матчится."""
        if self.find_button(img, "corruption_search") is not None:
            return True
        return self.find_button(img, "corruption_dialog") is not None

    def corruption_screen(self, img):
        """Экран режима «Элитная скверна»: 'dialog' (диалог поиска на вкладке
        скверны — видна кнопка «Поиск»), 'boss_panel' (панель босса с «Штурм»),
        'preview' (превью с «Начать Штурм»), 'preview_low_energy' (то же превью,
        но энергии не хватает и кнопка заменена на «Увеличить энергию»),
        иначе None.

        Порядок проверок важен: «Начать Штурм» встречается только в превью,
        поэтому проверяется первым; «Штурм» есть и на панели босса."""
        if self.find_button(img, "start_assault") is not None:
            return 'preview'
        if self.find_button(img, "boost_energy") is not None:
            return 'preview_low_energy'
        if self.find_button(img, "corruption_search") is not None:
            return 'dialog'
        if self.find_button(img, "assault") is not None:
            return 'boss_panel'
        return None

    def on_world_map(self, img):
        """True только если это чистая отзум-карта мира: матчим легенду
        «Моя территория/…» в top-right (её нет на зум-ине/в меню/полном UI).
        Guard: движок действует лишь когда True (иначе тычет UI-кнопки как
        цели — золотой «Альянс» ловится как босс и т.п.)."""
        x, y, w, h = self.cfg.worldmap_legend_region
        crop = img[y:y + h, x:x + w]
        tpl = self._state_tpl("worldmap_legend")
        if tpl is None or crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
            return False
        score = float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())
        return score >= self.cfg.worldmap_threshold

    def on_game_view(self, img):
        """Мы в игре на игровом виде — при ЛЮБОМ зуме.

        Якорь — иконка молнии в HUD энергии (не цифры: они меняются).
        Нужен отдельно от on_world_map, потому что в режиме скверны камера
        часто стоит в зум-ине после follow-cam, а легенды карты там нет —
        без этого якоря сторож считал бы нормальную работу аномалией.

        Под модальными диалогами игра блюрит фон, поэтому сквозь чужой экран
        якорь не протекает. Замер по референс-кадрам: игровые виды
        0.820…1.000, модалки 0.519/0.544 -> порог 0.7 посреди разрыва."""
        x, y, w, h = self.cfg.hud_energy_region
        crop = img[y:y + h, x:x + w]
        tpl = self._state_tpl("hud_energy")
        if tpl is None or crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
            return False
        score = float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())
        return score >= self.cfg.hud_energy_threshold

    def classify_screen(self, img):
        """Что сейчас на экране — один ответ вместо россыпи предикатов.

        Порядок сверху вниз по слоям: сначала то, что перекрывает остальное,
        иначе окно энергии поверх превью опозналось бы как превью.

        base_view проверяется РАНЬШЕ game_view: HUD энергии в базе тоже виден
        (замер 0.911), и якорь «мы в игре» сказал бы «всё нормально» — а
        дальше по флоу идёт слепой тап по лупе."""
        if self.exit_dialog_open(img):
            return 'exit_dialog'
        if self.energy_window_open(img):
            return 'energy_window'
        screen = self.corruption_screen(img)
        if screen is not None:
            return screen
        join = self.join_screen(img)
        if join == 'list':
            return 'join_list'
        if join is not None:
            return 'join_preview'
        if self.on_world_map(img):
            return 'world_map'
        if self.on_base_view(img):
            return 'base_view'
        if self.on_game_view(img):
            return 'game_view'
        return 'unknown'

    def _match_region(self, img, name, region):
        """Скор шаблона в фиксированной полосе. Полоса, а не весь кадр: это
        режет ложные матчи и ускоряет проверку."""
        x, y, w, h = region
        crop = img[y:y + h, x:x + w]
        tpl = self._state_tpl(name)
        if tpl is None or crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
            return 0.0
        return float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())

    def alliance_war_open(self, img):
        """Открыто ли окно «Война альянсов» — на любой вкладке.

        Якорь — заголовок окна: вкладка для этого не годится (активная и
        неактивная выглядят по-разному, урок вкладки «Элитная скверна»), а
        бегущие баннеры объявлений проходят ниже заголовка и его не портят."""
        score = self._match_region(img, "alliance_war", self.cfg.alliance_war_region)
        return score >= self.cfg.alliance_war_threshold

    def join_screen(self, img):
        """Экран режима присоединения: 'list' (окно со сборами), 'preview'
        (превью с «Отправиться»), 'preview_low_energy' (та же кнопка подменена
        на «Увеличить энергию»), иначе None.

        Порядок важен: «Увеличить энергию» проверяется первой, потому что она
        стоит НА МЕСТЕ «Отправиться» и обе кнопки в кадре одновременно не живут.

        Свой шаблон кнопки: dispatch.png включает строку цены «⚡ 10», а
        вступление бесплатное."""
        if self.find_button(img, "boost_energy") is not None:
            return 'preview_low_energy'
        if self.find_button(img, "join_dispatch") is not None:
            return 'preview'
        if self.alliance_war_open(img):
            return 'list'
        return None

    def on_base_view(self, img):
        """Мы в базе (не на карте мира).

        Якорь — сама кнопка «Мир» в правом нижнем углу: на карте мира на её
        месте стоит кнопка дома, поэтому спутать их нельзя. Ищем в узкой
        полосе угла, как worldmap_legend: это режет ложные матчи.

        Замер по референс-кадрам: база 1.00, все прочие 28 кадров <= 0.27."""
        x, y, w, h = self.cfg.world_button_region
        crop = img[y:y + h, x:x + w]
        tpl = self._state_tpl("world_button")
        if tpl is None or crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
            return False
        score = float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())
        return score >= self.cfg.world_button_threshold

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

    def active_squads(self, img):
        """Число активных отрядов из виджета «Отряд N/4» (левый верх) —
        главный гейт режима «Элитная скверна»: N < squad_total = есть куда слать.

        Виджет плавает по вертикали между кадрами (замер: 252 vs 274), поэтому
        ищем якорь-слово «Отряд» шаблоном в полосе и читаем цифру по фикс.
        смещению от матча. Виджета нет -> 0 (все отряды дома). Якорь есть, но
        цифра не прочлась -> squad_total: лучше лишний раз подождать, чем
        послать отряд вслепую."""
        bx, by, bw, bh = self.cfg.squad_header_band
        band = img[by:by + bh, bx:bx + bw]
        tpl = self._state_tpl("squad_header")
        if tpl is None or band.shape[0] < tpl.shape[0] or band.shape[1] < tpl.shape[1]:
            return 0
        _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(band, tpl, cv2.TM_CCOEFF_NORMED))
        if score < self.cfg.squad_header_threshold:
            return 0
        mx, my = bx + loc[0], by + loc[1]
        dx, dy, w, h = self.cfg.squad_count_offset
        n = self.reader.read(img, (mx + dx, my + dy, w, h))
        # 0 — валидное значение: виджет может висеть с «Отряд 0/4», когда все
        # отряды дома (а может и вовсе отсутствовать — оба состояния бывают).
        if n is None or not (0 <= n <= self.cfg.squad_total):
            return self.cfg.squad_total
        return n

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
        """Кнопка по шаблону -> Box (центр + размер шаблона) или None.

        Размер отдаём наружу, потому что тап должен приходить в случайную
        точку внутри кнопки, а не всегда в её центр."""
        path = os.path.join(self.cfg.templates_dir, f"{name}.png")
        tpl = cv2.imread(path, cv2.IMREAD_COLOR)
        if tpl is None:
            return None
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if maxv < self.cfg.template_match_threshold:
            return None
        th, tw = tpl.shape[:2]
        return Box(maxloc[0] + tw // 2, maxloc[1] + th // 2, tw, th)

    def find_all(self, img, name, region=None, threshold=None, min_dist=None):
        """Все совпадения шаблона, а не лучшее (как find_button): карточек и
        слотов в кадре несколько.

        Соседние пики одного объекта подавляются: matchTemplate даёт кляксу
        совпадений вокруг каждой находки, без подавления один «+» превратился
        бы в десяток."""
        tpl = self._state_tpl(name)
        if tpl is None:
            return []
        x0, y0 = 0, 0
        area = img
        if region is not None:
            x0, y0, w, h = region
            area = img[y0:y0 + h, x0:x0 + w]
        th, tw = tpl.shape[:2]
        if area.shape[0] < th or area.shape[1] < tw:
            return []
        thr = self.cfg.template_match_threshold if threshold is None else threshold
        res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= thr)
        gap = min_dist if min_dist is not None else max(tw, th) // 2
        out = []
        for x, y in sorted(zip(xs, ys), key=lambda p: -res[p[1], p[0]]):
            cx, cy = x0 + int(x) + tw // 2, y0 + int(y) + th // 2
            if any(abs(cx - b.x) < gap and abs(cy - b.y) < gap for b in out):
                continue
            out.append(Box(cx, cy, tw, th))
        out.sort(key=lambda b: (b.y, b.x))
        return out

    def assault_call_icon(self, img):
        """Красная иконка-череп «кто-то набирает помощников» или None.
        Видна и на карте, и в базе. Бейдж с числом и таймер в шаблон не
        входят — они меняются каждую секунду."""
        return self.find_button(img, "assault_call")

    def refresh_button(self, img):
        """Жёлтая «Обновить» внизу окна сборов или None. Появляется, только
        когда список устарел, поэтому её отсутствие — не ошибка."""
        return self.find_button(img, "join_refresh")

    def join_cards(self, img):
        """Карточки сборов «Элитная скверна» в окне, сверху вниз.

        Якорь карточки — надпись «Элитная скверна» слева. Слоты и таймер
        отсчитываются ОТ ЯКОРЯ, а не по фиксированным координатам: список
        съезжает по вертикали. Тот же приём спас рефилл склянкой — строка
        ищется по иконке, а не по координате из конфига."""
        anchors = self.find_all(img, "join_card", region=self.cfg.join_list_region,
                                threshold=self.cfg.join_card_threshold)
        cards = []
        for i, a in enumerate(anchors):
            bottom = (anchors[i + 1].y if i + 1 < len(anchors)
                      else a.y + self.cfg.join_card_height)
            dx, dy, bw, bh = self.cfg.join_card_plus_band
            band_h = min(bh, max(0, bottom - (a.y + dy)))
            slots = self.find_all(img, "join_slot",
                                  region=(a.x + dx, a.y + dy, bw, band_h),
                                  threshold=self.cfg.join_slot_threshold)
            slots.sort(key=lambda b: b.x)
            tx, ty, tw, th = self.cfg.join_card_timer_region
            cards.append(JoinCard(y=a.y, slots=slots,
                                  seconds=self._read_seconds(img, (a.x + tx, a.y + ty, tw, th))))
        return cards

    def _read_seconds(self, img, region):
        """Остаток таймера «В команде 00:00:35» как целое число.

        Двоеточия отсеиваются фильтром компонент, поэтому «00:00:35» читается
        как 35, а «00:01:20» — как 120. Точность и не нужна: решение бинарное
        («меньше порога в 10 секунд или нет»), а любое время с минутами даёт
        заведомо трёхзначное число, то есть «времени хватает»."""
        return self.reader.read(img, region)

    def read_energy(self, img):
        """Энергия из HUD. Белые цифры лежат ПОВЕРХ зелёной полосы заполнения,
        поэтому читаем с отсечкой по яркости, а не через Otsu (иначе полоса
        склеивается с цифрами: 50 читалось как 9)."""
        return self.reader.read(img, self.cfg.region_energy,
                                white_threshold=self.cfg.energy_white_threshold)

    def read_deployed(self, img):
        return self.reader.read(img, self.cfg.region_deployed)

    def read_flasks(self, img):
        return self.reader.read(img, self.cfg.region_flasks)

    def squad_slot(self, n):
        return self.cfg.squad_slots[n]
