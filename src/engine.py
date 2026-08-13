# src/engine.py
import os
import time
import traceback
from src.models import GameState, Action, nearest
from src.cancel import Cancel
from src.decide import decide
from src.human import Human
from src.version import VERSION

class BotEngine:
    """Цикл фарма. Один отряд-на-задачу за раз (v1 последовательный):
    отряд занят -> ждём; свободен/«Возвращение» -> шлём следующую цель.
    Приоритет: босс («Штурм», отр.1) -> моб («Атака», отр.2) -> explore.

    dry_run (cfg.dry_run): читаем экран и ЛОГИРУЕМ решение, но НЕ тапаем —
    для проверки детекции/логики на живой игре без действий."""

    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep,
                 corruption=None, join=None, thief=None, zoom=None,
                 human=None, cancel=None, watchdog=None):
        self.driver = driver
        self.vision = vision
        self.actions = actions
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        # если human не передан — свой, но спящий через тот же sleep (тесты
        # подсовывают фейковый sleep и должны видеть паузы именно там)
        self.human = human if human is not None else Human(cfg, sleep=sleep)
        # cancel всегда объект, а не None: точки проверки читаются
        # как `if self.cancel.stopped()`, без проверок на None в каждой
        self.cancel = cancel if cancel is not None else Cancel()
        self.corruption = corruption   # CorruptionActions для режима «Элитная скверна»
        self.join = join               # JoinActions для режима «Присоединиться к штурму»
        self.thief = thief             # ThiefActions для режима «Поиск вора»
        self.zoom = zoom               # ZoomKeeper: тот же режим, вид карты
        self.watchdog = watchdog       # сторож экрана; None -> движок работает как раньше
        self.flasks = None
        self.skip_targets = set()   # непроходимые боссы / фантомы (по позиции) — не выбираем
        # Конвейер: превью следующего вора открыто и ждёт только отряда.
        self._armed = False
        self._armed_polls = 0
        # Энергия ДО отправки (снята на зум-скулле в _arm_next) и цель,
        # которую взвели — нужны для подтверждения отправки по энергии
        # (см. _dispatch_confirmed): живой прогон 2026-08-13 поймал заход
        # 79->79, отрапортованный игрой как 'dispatched', хотя энергия не
        # потратилась ни на йоту.
        self._armed_energy_before = None
        self._armed_target = None
        self._offmap_pinches = 0    # подряд попыток авто-отзума когда не на карте
        self._no_progress = 0       # подряд итераций без отправки (в любом активном режиме)
        self._zoom_fails = 0        # подряд неудачных приведений зума
        # неопознанный экран считаем ОТДЕЛЬНО от сломанного щипка: у них
        # разные лечения (переждать против «позвать человека») и разный запас
        self._zoom_unknowns = 0
        # подряд попыток закрыть СВОЮ модалку тапом: закрытие либо срабатывает
        # сразу, либо не сработает вовсе (тап мимо, игра зависла) — без
        # предела бот крутится вечно, а сторож это не ловит (экран распознан)
        self._modal_closes = 0
        self._searches = 0          # «Поисков» подряд без набора целей
        # ПОДТВЕРЖДЁННЫЕ вступления в чужие штурмы (режим join). Считает движок,
        # а не раннер: подтверждение видно только здесь, а «dispatched» от
        # JoinActions — всего лишь «тап прошёл», и живьём уже оказывался ложным.
        self.joins = 0

    def start(self):
        # Версия — первой строкой лога: это самое ценное место для неё, лог и
        # присылают человеку, когда бот ведёт себя не так, как ожидалось.
        self.log(f"Last Asylum Bot {VERSION}")
        if self.cfg.dry_run:
            self.flasks = 10 ** 9        # в dry-run не открываем энергоокно
            self.log("Старт (DRY-RUN: тапов не будет).")
        elif self.cfg.strategy == "corruption":
            # «В наличии: N» в окне энергии перекрыт счётчиком количества и
            # читается только ПОСЛЕ применения склянок. Поэтому на старте
            # остаток неизвестен: первый рефилл разрешён и он же его покажет.
            self.flasks = None
            self.log("Старт («Элитная скверна»). Остаток склянок прочитаю "
                     "из игры после первого рефилла.")
        elif self.cfg.strategy == "join":
            # flasks остаётся None намеренно: ветка нужна лишь затем, чтобы
            # режим не провалился в ветку по умолчанию (map), которая читает
            # flasks_left() через OCR карты. Ни энергия, ни склянки в этом
            # режиме не тратятся, читать их неоткуда и незачем.
            self.flasks = None
            self.log("Старт (присоединение к чужим штурмам). Энергия и склянки "
                     "в этом режиме не тратятся.")
        elif self.cfg.strategy == "thief":
            # Как и в скверне, остаток склянок читается только ПОСЛЕ первого
            # применения — до этого его перекрывает счётчик количества.
            self.flasks = None
            self.log("Старт («Поиск вора»). Остаток склянок прочитаю "
                     "из игры после первого рефилла.")
        else:
            self.flasks = self.actions.flasks_left()
            self.log(f"Старт. Склянок: {self.flasks}")

    def _squad_ready(self, state):
        """Готов ли слать следующую цель по состоянию отряда."""
        if state == 'idle':
            return True
        if state == 'returning' and self.cfg.send_next_on_return:
            return True
        return False

    def read_state(self, img):
        energy = self.vision.read_energy(img)
        targets = self.vision.find_targets(img)
        return GameState(
            flasks=self.flasks if self.flasks is not None else 10**9,
            energy=energy if energy is not None else 999,   # не прочли -> не рефиллим спекулятивно
            deployed=0, targets=targets,
            screen_w=self.cfg.screen_w, screen_h=self.cfg.screen_h,
        )

    @staticmethod
    def _target_key(t):
        return (t.kind, round(t.x / 20), round(t.y / 20))

    def _account_flasks(self, used_before):
        """«В наличии: N» точнее локального учёта, но если оно не прочлось —
        считаем потраченное локально и НЕ молчим об этом. Раньше эта ветка
        только читала last_flask_stock: если «В наличии» не прочлось,
        self.flasks оставался None, а refill = (self.flasks is None) разрешал
        бы рефилл навсегда — порог склянок молча переставал действовать.

        Один метод на оба пути отправки (обычный и конвейерный): двух копий
        этого учёта в проекте уже быть не должно."""
        spent = self.thief.flasks_used - used_before
        if self.thief.last_flask_stock is not None:
            self.flasks = self.thief.last_flask_stock
        elif spent and self.flasks is not None:
            self.flasks = max(0, self.flasks - spent)
        elif spent:
            self.log("  остаток склянок прочитать не удалось — порог не действует")
        if spent:
            self.log(f"  склянок потрачено {spent}, осталось {self.flasks}")

    def _refill_allowed(self):
        return self.flasks is None or self.flasks > self.cfg.flask_stop_threshold

    def _dispatch_confirmed(self, energy_before):
        """Действительно ли отправка потратила энергию — а не просто закрыла
        превью вхолостую. Живой прогон 2026-08-13 (раунд исправления 1,
        задача 7): цепочка энергии 98->88->78->79->69->59->49 — между
        второй и третьей отправкой энергия успела САМА отрасти на 1
        (78->79), а сама третья отправка прошла как 79->79 и не потратила
        ничего; движок при этом отрапортовал 'dispatched' и обнулил
        счётчик провалов. Гипотеза «взвели того же вора, к которому уже
        идёт отряд» (камера центрируется на нём) проверкой по координатам
        НЕ подтвердилась — 240 px от центра у холостого случая против 194
        и 464 px у успешных, — поэтому чинится сам факт ложного успеха, а
        не предполагаемый механизм (он неизвестен).

        Вор стоит 10 энергии (замер спеки), но она сама отрастает по ходу
        цикла — порог не РОВНО 10, а НЕ МЕНЬШЕ 5 (cfg.thief_dispatch_energy_drop):
        разделяет 0 и 10 с запасом и не путает естественный прирост с
        подтверждением.

        Читать энергию можно не всегда (до — только на зум-скулле, после —
        как только закрылось превью) -> любое из двух чтений может дать
        None. Тогда сравнивать нечего: ложная тревога тут дороже пропуска,
        считаем отправку успешной, как раньше, но не молчим об этом в
        логе — тот же приём, что у нечитаемого остатка склянок в
        _account_flasks."""
        energy_after = self.vision.read_energy(self.driver.screenshot())
        if energy_before is None or energy_after is None:
            self.log("  энергию до/после отправки прочитать не удалось — "
                     "подтвердить не могу, считаю успешной")
            return True
        if energy_before - energy_after >= self.cfg.thief_dispatch_energy_drop:
            return True
        self.log(f"  отправка НЕ подтвердилась: энергия была {energy_before}, "
                 f"стала {energy_after} — прогрессом не считаю")
        return False

    def _corruption_iteration(self):
        """Режим «Элитная скверна»: гейт по числу активных отрядов «Отряд N/4»,
        отправка штурма пока есть свободные слоты. Все отряды в походе -> ждём;
        энергии не хватает и склянки тратить нельзя -> стоп.

        Тапа по карте нет (панель босса открывает сам «Поиск»), поэтому guard
        вида и авто-отзум тут не нужны."""
        # Сторож ПЕРЕД всем остальным: дальше идёт слепой тап по лупе
        # (78,1530), и если под ней не игра, а чужой экран — тап уйдёт мимо.
        if self.watchdog is not None:
            verdict = self.watchdog.check()
            if verdict == 'stop':
                return Action('stop')
            if verdict == 'recovered':
                return None
        img = self.driver.screenshot()
        active = self.vision.active_squads(img)
        limit = self.cfg.squad_limit()
        if active >= limit:
            self.log(f"Занято {active} из {limit} разрешённых, ждём.")
            self.sleep(self.human.idle_s(self.cfg.corruption_poll_interval_s))
            return None

        energy = self.vision.read_energy(img)
        # Разрешаем тратить склянку, пока учтённый остаток выше порога.
        # Остаток «В наличии: N» читается только ПОСЛЕ применения склянок
        # (до этого его перекрывает счётчик количества). Поэтому пока остаток
        # неизвестен, разрешаем один рефилл — он же и покажет реальное число,
        # после чего порог начинает работать точно.
        refill = self.flasks is None or self.flasks > self.cfg.flask_stop_threshold
        if not refill:
            self.log(f"Склянок {self.flasks} <= порога "
                     f"{self.cfg.flask_stop_threshold} — склянки не тратим.")

        self.log(f"[отрядов={active}/{limit}] энергия={energy} "
                 f"склянок={self.flasks}" + (" (+рефилл разрешён)" if refill else "")
                 + " -> штурм скверны")
        if self.cfg.dry_run:
            self.sleep(1.0)
            return Action('assault_boss')

        used_before = self.corruption.flasks_used
        res = self.corruption.run_once(refill=refill)
        if res == 'stopped':
            # остановка по кнопке — не провал бота, счётчик провалов не трогаем
            self.log("  заход прерван по кнопке Стоп")
            return Action('stop')
        self.log(f"  Штурм скверны -> {res}")
        spent = self.corruption.flasks_used - used_before
        if self.corruption.last_flask_stock is not None:
            # прочитанное «В наличии: N» точнее локального учёта
            self.flasks = self.corruption.last_flask_stock
        elif spent and self.flasks is not None:
            self.flasks = max(0, self.flasks - spent)
        elif spent:
            # Вести остаток не от чего: ручного поля больше нет, а «В наличии»
            # не прочиталось. Молчать нельзя — порог сейчас не работает.
            self.log("  остаток склянок прочитать не удалось — порог не действует")
        if spent:
            self.log(f"  склянок потрачено {spent}, осталось {self.flasks}")

        if res == 'low_energy':
            # Превью — источник истины: игра сама сказала, что энергии мало.
            self.log("Энергии не хватает на штурм — стоп. Пополни энергию и запусти снова.")
            return Action('stop')

        if res == 'dispatched':
            self._no_progress = 0
            after = self.vision.active_squads(self.driver.screenshot())
            if after <= active:
                self.log(f"  внимание: отрядов было {active}, стало {after} — "
                         f"отправка могла не пройти")
        else:
            self._no_progress += 1
            if self._no_progress >= self.cfg.max_search_failures:
                self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
                return Action('stop')
        return Action('assault_boss')

    def _join_iteration(self):
        """Режим «присоединяться к чужим штурмам»: гейт тот же, что у своего
        штурма (число активных отрядов), но вместо запуска сбора бот ищет чужой.

        Сборов нет — это НЕ провал: просто ждём и пробуем снова. Провалом
        считается только незнакомый экран/несостоявшийся шаг."""
        if self.watchdog is not None:
            verdict = self.watchdog.check()
            if verdict == 'stop':
                return Action('stop')
            if verdict == 'recovered':
                return None
        img = self.driver.screenshot()
        active = self.vision.active_squads(img)
        limit = self.cfg.squad_limit()
        if active >= limit:
            self.log(f"Занято {active} из {limit} разрешённых, ждём.")
            self.sleep(self.human.idle_s(self.cfg.corruption_poll_interval_s))
            return None

        energy = self.vision.read_energy(img)
        # Склянки и энергия тут ни при чём: вступление в чужой штурм бесплатное,
        # энергия уходит только на СВОЙ штурм. Читаем её лишь для лога.
        self.log(f"[отрядов={active}/{limit}] энергия={energy} -> ищу чужой сбор")
        if self.cfg.dry_run:
            self.sleep(1.0)
            return Action('join_assault')

        res = self.join.run_once()
        if res == 'stopped':
            self.log("  заход прерван по кнопке Стоп")
            return Action('stop')
        self.log(f"  Присоединение -> {res}")

        if res == 'low_energy':
            self.log("Игра просит энергию за присоединение, хотя оно бесплатное "
                     "— стоп, нужен человек.")
            return Action('stop')
        if res == 'no_calls':
            self.log("Сборов сейчас нет, жду.")
            self.sleep(self.human.idle_s(self.cfg.corruption_poll_interval_s))
            return None

        if res == 'dispatched' and not self._join_confirmed(active):
            # Отправку ПРОВЕРЯЕМ, а не объявляем: живой прогон 2026-08-10 дал
            # 'dispatched' на истёкшем сборе, отряд не вышел, а _no_progress
            # обнулился — бот молча крутился вхолостую. Неподтверждённая
            # отправка идёт по ветке провала; если мы при этом остались внутри
            # окна сборов, следующий заход это увидит и приберётся (см.
            # JoinActions.run_once).
            res = 'unconfirmed'

        if res == 'dispatched':
            self._no_progress = 0
            self.joins += 1
        else:
            self._no_progress += 1
            if self._no_progress >= self.cfg.max_search_failures:
                self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
                return Action('stop')
        return Action('join_assault')

    def _join_confirmed(self, before):
        """Вырос ли счётчик «Отряд N/4» после тапа по «Отправиться».

        Тот же приём, что у своего штурма (см. _corruption_iteration), но
        строже: там расхождение только логируется, здесь оно отменяет успех.
        Причина — живой прогон: сбор истёк между обновлением списка и тапом,
        JoinActions отдал 'dispatched', отряд не вышел.

        Ждём в цикле, а не смотрим один кадр: виджет отрядов перекрыт окном
        сборов (замер по кадрам 32/34 — active_squads там всегда 0), поэтому
        поверить счётчику можно, только когда игра вернёт нас на карту.
        Не дождались -> отправка не подтверждена: ложный успех тут дороже
        лишнего захода."""
        after = before
        rounds = max(1, int(self.cfg.panel_verify_timeout_s / 0.5))
        for i in range(rounds):
            after = self.vision.active_squads(self.driver.screenshot())
            if after > before:
                return True
            if i < rounds - 1:
                self.sleep(self.human.poll_s(0.5))
        self.log(f"  отправка НЕ подтвердилась: отрядов было {before}, стало "
                 f"{after} — сбор мог истечь, вступлением не считаю")
        return False

    def _thief_iteration(self):
        """Режим «Поиск вора»: ждём на зум-ине, бьём на отзуме.

        Такая форма не из вкуса, а из замера: виджет «Отряд» на отзуме не
        рисуется вовсе, и гейт там всегда видел бы «свободен». Зато отзум
        даёт втрое больше целей в кадре, поэтому два щипка на убийство
        (наружу перед выбором цели, внутрь после отправки) — честная цена
        при цикле ≈70 секунд."""
        if self.watchdog is not None:
            verdict = self.watchdog.check()
            if verdict == 'stop':
                return Action('stop')
            if verdict == 'recovered':
                return None

        # Взведён: превью следующего вора уже открыто, ждём только отряд.
        # Проверяем ДО гейтов зума — под модалкой зума не существует.
        if self._armed:
            return self._thief_armed_iteration()

        # 1. Гейт отряда — только на зум-ине, виджета на отзуме нет.
        gate = self._zoom_gate("close")
        if gate is not True:
            return gate
        img = self.driver.screenshot()
        squad = self.vision.squad_state(img)
        if not self._squad_ready(squad):
            self.log(f"Отряд занят ({squad}), ждём.")
            self.sleep(self.human.idle_s(2.0))
            return None

        # 2. Вид для выбора цели.
        gate = self._zoom_gate("skull")
        if gate is not True:
            return gate
        # Сбрасываем счётчик ЗДЕСЬ, один раз за итерацию — когда оба гейта
        # подряд привелись и итерация реально дошла до выбора цели. Сброс
        # ВНУТРИ _zoom_gate (по каждому успеху отдельно) обнулял бы счётчик
        # первым же гейтом «close», даже если «skull» стабильно не
        # приводится: тогда zoom_fail_limit не достигался бы НИКОГДА, и бот
        # вечно щипал бы туда-сюда молча вместо честной остановки.
        self._zoom_fails = 0
        self._zoom_unknowns = 0
        self._modal_closes = 0
        img = self.driver.screenshot()
        energy = self.vision.read_energy(img)
        targets = [t for t in self.vision.leveled_targets(img)
                   if t.level == self.cfg.thief_level
                   and self._target_key(t) not in self.skip_targets]

        # 3. Целей мало — перевозим камеру «Поиском». Но порог УСТУПАЕТ:
        # после thief_searches_per_wave заходов бьём то, что видим, иначе
        # редкая волна дала бы вечный цикл «ищу — мало — ищу» при живой
        # цели перед носом.
        if (len(targets) < self.cfg.thief_min_targets
                and self._searches < self.cfg.thief_searches_per_wave):
            self.log(f"[целей={len(targets)}] энергия={energy} -> «Поиск»")
            return self._thief_search()
        if not targets:
            # Бюджет «Поисков» исчерпан, а целей всё ещё нет. Раньше отсюда
            # снова звали _thief_search() — то есть ещё один «Поиск» вместо
            # обещанного логом «жду волну». Единственный штатный выход из
            # цикла (игра ответит 'no_wave') живьём НИ РАЗУ не подтверждался
            # ни на одном прогоне — полагаться на него как на единственный
            # тормоз нельзя. Спим сами, не дожидаясь честности игры.
            self.log("Целей нет и «Поиск» их не даёт — жду волну.")
            return self._thief_wait_for_wave()

        # 4. Бьём ближайшего к центру: после «Поиска» камера стоит на воре.
        self._searches = 0
        refill = self.flasks is None or self.flasks > self.cfg.flask_stop_threshold
        target = nearest(targets, self.cfg.screen_w // 2, self.cfg.screen_h // 2)
        self.log(f"[целей={len(targets)}] энергия={energy} склянок={self.flasks}"
                 + (" (+рефилл разрешён)" if refill else "")
                 + f" -> вор @({target.x},{target.y})")
        if self.cfg.dry_run:
            self.sleep(1.0)
            return Action('attack_mob')

        used_before = self.thief.flasks_used
        res = self.thief.attack(target, refill=refill)
        self.log(f"  Удар по вору -> {res}")
        self._account_flasks(used_before)
        if res == 'stopped':
            self.log("  заход прерван по кнопке Стоп")
            return Action('stop')
        if res == 'low_energy':
            self.log("Энергии не хватает — стоп. Пополни энергию и запусти снова.")
            return Action('stop')
        if res == 'not_thief':
            # Ожидаемый исход неразличимых иконок, а НЕ провал: иначе три
            # подряд обычных моба выключили бы бота на ровном месте.
            self.skip_targets.add(self._target_key(target))
            return Action('attack_mob')
        if res == 'missed':
            self.skip_targets.add(self._target_key(target))

        # Тот же ложный успех возможен и здесь: `energy` — значение,
        # прочитанное ДО удара чуть выше в этой же итерации. Один метод на
        # оба пути отправки (обычный и конвейерный) — см. _dispatch_confirmed.
        if res == 'dispatched' and not self._dispatch_confirmed(energy):
            self.skip_targets.add(self._target_key(target))
            res = 'unconfirmed'
        if res == 'dispatched':
            self._no_progress = 0
            self._arm_next()
        else:
            self._no_progress += 1
            if self._no_progress >= self.cfg.max_search_failures:
                self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
                return Action('stop')
        return Action('attack_mob')

    def _zoom_gate(self, want):
        """Приводит карту к ступени want. True — можно продолжать; иначе
        вызывающая ветка обязана вернуть то, что здесь возвращено
        (None или Action('stop')).

        ВАЖНО: успех НЕ сбрасывает self._zoom_fails здесь — гейтов в
        итерации два («close» и «skull»), и сброс по каждому успеху
        отдельно обнулял бы счётчик первым же гейтом, даже если второй
        стабильно не приводится: zoom_fail_limit тогда не достигался бы
        НИКОГДА (ревью Task 7, раунд 1, Important A). Сброс — забота
        вызывающего кода, один раз за итерацию, когда оба гейта пройдены.

        zoom.ensure() сам проверяет отмену внутри лестницы щипков (паузы
        между ними ~1.3 с — окно для Стопа реальное) и при Стопе тоже
        отдаёт False, не тапнув — снаружи это неотличимо от настоящей
        невозможности привестись. Тот же класс бага уже чинили в
        ThiefActions.search() (коммит 33cb819): если списать Стоп в обычный
        провал зума, он попадёт в счётчик поломок бота, а лог соврёт про
        причину остановки."""
        if self.zoom.ensure(want):
            return True
        if self.cancel.stopped():
            # Соседние точки выхода по Стопу пишут причину в лог (см. атаку
            # и «Поиск» ниже) — здесь та же дисциплина: лог единственный
            # диагностический артефакт проекта, и молчаливая остановка
            # читалась бы человеком как «бот сам умер», а не «сам нажал».
            self.log("  заход прерван по кнопке Стоп (во время приведения зума)")
            return Action('stop')
        return self._zoom_failed()

    # Экраны, которые бот открывает сам и умеет закрыть тапом по затемнению.
    # Имена — ровно те, что возвращает Vision.classify_screen.
    _OWN_MODALS = ('thief_tab', 'thief_preview', 'energy_window',
                   'preview', 'preview_low_energy', 'dialog', 'boss_panel',
                   'join_list', 'join_preview')

    def _zoom_failed(self):
        """Зум не привёлся. Что делать — зависит от ПРИЧИНЫ.

        «Щипок не двигает карту» — поломка: копим неудачи подряд и зовём
        человека, как раньше. Работать на чужом зуме нельзя: детекция
        площадей врёт, и бот тапал бы мимо целей.

        «Экран не опознан» — чаще временная помеха. Живьём (прогон 3,
        2026-08-13) всплывший баннер прогресса закрыл якорь HUD энергии
        (скор 0.364 при пороге 0.7), и бот встал за ШЕСТЬ секунд с «нужен
        человек», хотя баннер уходит сам. Такие ждём дольше и отдельным
        счётчиком — той же политикой, что у сторожа: ждать без единого тапа.

        Исключение — СВОЯ модалка (превью, окно энергии, меню режима):
        ожиданием она не уйдёт, её закрывают. Это не провал зума, иначе три
        всплывших окна подряд выключали бы бота.

        У закрытия модалки СВОЙ предел (Critical, ревью раунда 1): без него
        промахнувшийся тап или зависшая игра держат бота в вечном `None`, а
        сторож это не ловит — экран распознан, просто это не карта. Предел
        маленький: закрытие либо срабатывает сразу, либо не сработает вовсе,
        это не помеха, которую пережидают.

        Возвращает None (ждём и пробуем снова) или Action('stop')."""
        if getattr(self.zoom, 'last_failure', 'stuck') == 'unknown_screen':
            screen = self.vision.classify_screen(self.driver.screenshot())
            if screen in self._OWN_MODALS:
                self._modal_closes += 1
                if self._modal_closes >= self.cfg.modal_close_limit:
                    self.log(f"«{screen}» не закрывается {self._modal_closes} раз "
                             f"подряд — стоп, нужен человек.")
                    return Action('stop')
                self.log(f"  поверх карты открыт «{screen}» — закрываю и пробую снова")
                self.actions.close_preview()
                self.human.after_tap(0.6)
                return None
            self._zoom_unknowns += 1
            if self._zoom_unknowns >= self.cfg.zoom_unknown_limit:
                self.log(f"Экран не опознан {self._zoom_unknowns} раз подряд — "
                         f"стоп, нужен человек.")
                return Action('stop')
            self.log(f"  экран не опознан ({self._zoom_unknowns}/"
                     f"{self.cfg.zoom_unknown_limit}) — жду, помеха может уйти сама")
            self.sleep(self.human.idle_s(self.cfg.zoom_unknown_wait_s))
            return None

        self._zoom_fails += 1
        if self._zoom_fails >= self.cfg.zoom_fail_limit:
            self.log(f"Зум не приводится {self._zoom_fails} раз подряд — стоп, нужен человек.")
            return Action('stop')
        self.sleep(self.human.idle_s(2.0))
        return None

    def _thief_armed_iteration(self):
        """Взведён: превью следующего вора открыто и ждёт освобождения отряда.

        Ради этого состояния конвейер и делается: подготовка (тап цели,
        панель, «Атака», превью — замер 18 с) уходит ПОД марш, а не после
        него. Гейт читается по карточке отряда в самом превью: верхний
        виджет «Отряд» превью перекрывает."""
        img = self.driver.screenshot()
        if self.vision.classify_screen(img) != 'thief_preview':
            self.log("Превью закрылось само — снимаю взвод.")
            self._armed = False
            return Action('attack_mob')

        state = self.vision.preview_squad_state(img, self.cfg.mob_squad)
        # None = карточку не опознали. Трактуем как «занят»: лишнее ожидание
        # дешевле отправки вслепую.
        if state in (None, 'busy'):
            self._armed_polls += 1
            if self._armed_polls >= self.cfg.armed_poll_limit:
                self.log("Отряд не освободился за отведённое время — закрываю превью.")
                self.actions.close_preview()
                self._armed = False
                return None
            self.sleep(self.human.idle_s(self.cfg.armed_poll_s))
            return None

        self.log(f"Отряд {self.cfg.mob_squad}: {state} -> отправляю из готового превью")
        used_before = self.thief.flasks_used
        res = self.thief.fire(refill=self._refill_allowed())
        self._armed = False
        self.log(f"  Отправка -> {res}")
        self._account_flasks(used_before)
        if res == 'stopped':
            self.log("  заход прерван по кнопке Стоп")
            return Action('stop')
        if res == 'low_energy':
            self.log("Энергии не хватает — стоп. Пополни энергию и запусти снова.")
            return Action('stop')
        # Игра может отрапортовать 'dispatched', ничего не потратив (живой
        # прогон 2026-08-13: заход 79->79) — см. _dispatch_confirmed. Тот же
        # приём, что у неподтверждённого вступления в _join_iteration:
        # понижаем 'dispatched' до провала, дальше он идёт обычной веткой.
        if res == 'dispatched' and not self._dispatch_confirmed(self._armed_energy_before):
            self.skip_targets.add(self._target_key(self._armed_target))
            res = 'unconfirmed'
        if res == 'dispatched':
            self._no_progress = 0
            self._arm_next()
        else:
            self._no_progress += 1
            if self._no_progress >= self.cfg.max_search_failures:
                self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
                return Action('stop')
        return Action('attack_mob')

    def _arm_next(self):
        """Подготовить следующего вора, пока отряд в марше.

        Тихо выходит, если цели нет или взвод не удался: это не провал
        итерации, обычный цикл просто отработает как раньше."""
        if not self.cfg.thief_pipeline or self.cfg.dry_run:
            return
        if not self.zoom.ensure("skull"):
            return
        img = self.driver.screenshot()
        # Энергия ДО отправки — только здесь, на зум-скулле, HUD ещё виден:
        # внутри превью read_energy() отдаёт None (HUD там перекрыт).
        energy_before = self.vision.read_energy(img)
        targets = [t for t in self.vision.leveled_targets(img)
                   if t.level == self.cfg.thief_level
                   and self._target_key(t) not in self.skip_targets]
        if not targets:
            return
        target = nearest(targets, self.cfg.screen_w // 2, self.cfg.screen_h // 2)
        res = self.thief.arm(target)
        self.log(f"  взвод следующего вора @({target.x},{target.y}) -> {res}")
        if res == 'armed':
            self._armed = True
            self._armed_polls = 0
            self._armed_energy_before = energy_before
            self._armed_target = target
        elif res in ('not_thief', 'missed'):
            self.skip_targets.add(self._target_key(target))

    def _thief_search(self):
        """Заход «Поиск» и разбор его исхода."""
        if self.cfg.dry_run:
            self.sleep(1.0)
            return Action('attack_mob')
        res = self.thief.search()
        self.log(f"  «Поиск» -> {res}")
        if res == 'stopped':
            return Action('stop')
        if res == 'searched':
            self._searches += 1
            # Камера уехала: экранные координаты пропусков больше ничего не
            # значат, иначе бот пропускал бы новых воров в старых ячейках.
            self.skip_targets.clear()
            return Action('attack_mob')
        if res in ('no_wave', 'no_event'):
            return self._thief_wait_for_wave()
        self._no_progress += 1
        if self._no_progress >= self.cfg.max_search_failures:
            self.log(f"Нет отправок {self._no_progress} раз подряд — стоп, нужен человек.")
            return Action('stop')
        return Action('attack_mob')

    def _thief_wait_for_wave(self):
        """Сон до следующей волны воров. Общая точка для ДВУХ входов:
        «Поиск» ответил no_wave/no_event, и «бюджет Поисков исчерпан, а
        целей всё ещё нет» в _thief_iteration — раньше вторая ветка вместо
        сна снова звала _thief_search(), давая бесконечный цикл заходов в
        меню (см. правку по итогу финального ревью). Копий быть не должно.

        last_wave_seconds годится для обеих точек: ThiefActions.search()
        читает таймер волны при КАЖДОМ заходе в окно, а сюда бот попадает
        только после нескольких заходов подряд — таймер уже, скорее всего,
        известен."""
        wait = self.thief.last_wave_seconds
        if wait is None or wait <= 0:
            wait = self.cfg.thief_wave_poll_s
        wait = min(wait, self.cfg.thief_wave_max_sleep_s)
        self.log(f"Воров нет — сплю {int(wait)} с до следующей волны.")
        self._searches = 0
        self.skip_targets.clear()
        self.sleep(self.human.idle_s(wait))
        return None

    def one_iteration(self):
        # Стоп мог прийти, пока движок спал между итерациями
        if self.cancel.stopped():
            return Action('stop')
        if self.cfg.strategy == "join":
            return self._join_iteration()
        if self.cfg.strategy == "corruption":
            return self._corruption_iteration()
        if self.cfg.strategy == "thief":
            return self._thief_iteration()

        img = self.driver.screenshot()

        # GUARD: действуем только на чистой отзум-карте. После отправки камера
        # зумит за армией; на зум-ине детекция ловит UI-кнопки как цели.
        # Пробуем авто-отзум щипком; если не помогло N раз (вероятно меню) —
        # ждём человека.
        if not self.vision.on_world_map(img):
            if self._offmap_pinches < self.cfg.max_pinch_recover:
                self._offmap_pinches += 1
                self.log(f"Не на карте — авто-отзум щипком ({self._offmap_pinches}/{self.cfg.max_pinch_recover}).")
                self.driver.zoom_out()
                self.human.after_tap(1.5)
            else:
                self.log("Не на карте и щипок не помог (меню?) — жду человека.")
                self.sleep(self.human.idle_s(2.0))
            return None
        self._offmap_pinches = 0     # снова на карте -> сброс счётчика

        squad = self.vision.squad_state(img)
        state = self.read_state(img)

        # отряд в походе и слать рано -> ждём
        if not self._squad_ready(squad):
            self.log(f"Отряд занят ({squad}), ждём.")
            self.sleep(self.human.idle_s(2.0))
            return None

        # исключаем непроходимых боссов, помеченных ранее
        if self.skip_targets:
            state.targets = [t for t in state.targets
                             if self._target_key(t) not in self.skip_targets]

        action = decide(state, self.cfg)
        n_mob = sum(1 for t in state.targets if t.kind == 'mob')
        n_boss = sum(1 for t in state.targets if t.kind == 'boss')
        self.log(f"[отряд={squad}] энергия={state.energy} склянок={self.flasks} "
                 f"цели: мобов={n_mob} боссов={n_boss} -> {action.type}"
                 + (f" @({action.target.x},{action.target.y})" if action.target else ""))

        if self.cfg.dry_run:
            self.sleep(1.0)
            return action

        if action.type == 'stop':
            self.log("Стоп: склянок меньше порога.")
        elif action.type == 'refill':
            self.flasks = self.actions.refill_energy()
            self.log(f"Рефилл. Склянок осталось: {self.flasks}")
        elif action.type == 'assault_boss':
            res = self.actions.assault_boss(action.target)
            self.log(f"  Штурм босса -> {res}")
            if res == 'skip_unwinnable':
                self.skip_targets.add(self._target_key(action.target))
        elif action.type == 'attack_mob':
            res = self.actions.attack_mob(action.target)
            self.log(f"  Атака моба -> {res}")
        elif action.type == 'explore':
            self.driver.swipe(self.cfg.screen_w // 2, self.cfg.screen_h * 2 // 3,
                              self.cfg.screen_w // 2, self.cfg.screen_h // 3, 400)
        return action

    def _log_error(self, where, exc):
        self.log(f"[ОШИБКА в {where}] {type(exc).__name__}: {exc}")
        self.log(traceback.format_exc())
        self.log("Бот остановлен. Исправь причину и запусти снова.")

    def run(self, stop_event):
        try:
            if self.flasks is None:
                self.start()
        except Exception as exc:
            self._log_error("start", exc)
            return 'error'
        while True:
            if stop_event.is_set():
                return 'stopped_by_user'
            if os.path.exists(self.cfg.stop_file):
                return 'stop_file'
            try:
                action = self.one_iteration()
            except Exception as exc:
                self._log_error("one_iteration", exc)
                return 'error'
            if action is not None and action.type == 'stop' and not self.cfg.dry_run:
                return 'stop'
            self.sleep(self.human.idle_s(0.5))
