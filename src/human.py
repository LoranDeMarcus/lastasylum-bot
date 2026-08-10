# src/human.py
import math
import random
import time

class Human:
    """Человеческий разброс: куда именно приходит тап и сколько длится пауза.

    Чистая логика — ни ADB, ни экрана, ни файлов. На входе cfg и rng, на
    выходе числа, поэтому поведение проверяется статистикой и полностью
    воспроизводится сидом."""

    def __init__(self, cfg, rng=None, sleep=time.sleep):
        self.cfg = cfg
        self.rng = rng if rng is not None else random.Random()
        self._sleep = sleep

    # --- куда тапать ---

    def point_in(self, box):
        """Точка внутри кнопки: нормаль вокруг центра, ЖЁСТКО обрезанная
        внутренней областью (tap_inset). clamp, а не «обычно попадает»:
        промах по мелкой кнопке стоит дороже, чем недобор случайности."""
        return (self._axis(box.x, box.w), self._axis(box.y, box.h))

    def _axis(self, center, size):
        allowed = max(0.0, size / 2 * self.cfg.tap_inset)
        if allowed < 1:
            return int(center)
        d = self.rng.gauss(0, allowed / 2)          # ±2σ = граница области
        return int(round(center + max(-allowed, min(allowed, d))))

    def hold_ms(self):
        lo, hi = self.cfg.tap_hold_ms
        return int(self.rng.uniform(lo, hi))

    # --- сколько ждать ---

    def delay(self, kind):
        """Длительность паузы вида kind (сейчас единственный — 'react')."""
        lo, hi = getattr(self.cfg, f"delay_{kind}")
        return self._lognorm(lo, hi)

    def pause(self, kind):
        self._sleep(self.delay(kind))

    def _lognorm(self, lo, hi):
        """Логнормаль, обрезанная в [lo, hi]: медиана — геометрическое среднее
        границ, ±2σ накрывают диапазон. Равномерное распределение не годится —
        у него нет длинного хвоста вправо, и оно само по себе машинный признак."""
        median = math.sqrt(lo * hi)
        sigma = math.log(hi / lo) / 4
        v = median * math.exp(self.rng.gauss(0, sigma))
        return max(lo, min(hi, v))

    def after_tap(self, base_s):
        """Пауза после тапа. base_s — ОТКАЛИБРОВАННЫЙ минимум (ожидание
        анимации игры), поэтому её только растягиваем. Короче калибровки
        пауза стать не может, иначе посыплются верификации шагов."""
        lo, hi = self.cfg.delay_settle_mult
        self._sleep(base_s * self.rng.uniform(lo, hi) + self.delay('react'))

    def poll_s(self, base_s):
        """Интервал опроса в циклах ожидания экрана — тоже только вверх."""
        lo, hi = self.cfg.delay_poll
        return max(base_s, self.rng.uniform(lo, hi))

    # --- гоночный путь: успеть занять слот в чужом сборе ---

    def race_s(self):
        """Пауза «увидел экран -> нажал» там, где идёт гонка за место.

        Обычная delay_react (0.25..1.8 с) тут проигрывает: слот разбирают за
        секунду. Антибот-свойство при этом не теряется — мы ужимаем МАСШТАБ
        разброса, а не убираем сам разброс. Машину выдаёт одинаковость пауз,
        а не их краткость: человек, дерущийся за последнее место, жмёт ровно
        так же быстро."""
        lo, hi = self.cfg.delay_race
        return self._lognorm(lo, hi)

    def race_pause(self):
        self._sleep(self.race_s())

    def poll_race_s(self):
        """Интервал между кадрами в гонке.

        Здесь человечность не при чём совсем: снимок экрана игра не видит и
        отличить частый опрос от редкого не может. Наблюдаемы только тапы —
        их и разбрасывает race_s."""
        lo, hi = self.cfg.delay_poll_race
        return self.rng.uniform(lo, hi)

    def idle_s(self, base_s):
        """Пауза, когда делать нечего (все отряды заняты)."""
        lo, hi = self.cfg.delay_idle_mult
        return base_s * self.rng.uniform(lo, hi)
