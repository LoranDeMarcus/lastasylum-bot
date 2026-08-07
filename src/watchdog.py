# src/watchdog.py
import os
import time
import cv2
from src.cancel import Cancel

def safe_back(driver, vision, cfg, log=print, sleep=time.sleep, human=None):
    """Системная «назад» + страховка. На ЧИСТОЙ карте «назад» открывает
    «Выйти из игры?» — если это проглядеть, следующий слепой тап может
    подтвердить выход. Поэтому сразу проверяем и жмём «Отмена».

    Живёт здесь, а не в CorruptionActions: это общий приём восстановления,
    нужный и сторожу, и флоу штурма (двух копий быть не должно).

    human задан -> паузы человечные (и только длиннее калиброванных 0.6)."""
    pause = human.after_tap if human is not None else sleep
    driver.back()
    pause(0.6)
    img = driver.screenshot()
    if vision.exit_dialog_open(img):
        pos = vision.find_button(img, "exit_cancel")
        log("  открылся диалог выхода из игры -> Отмена")
        driver.tap(pos if pos is not None
                   else cfg.tap_box("exit_cancel", cfg.exit_cancel_xy))
        pause(0.6)

class Watchdog:
    """Сторож незнакомого экрана.

    Политика «ждать -> BACK -> стоп»: сначала просто ждём без единого тапа
    (реклама, подарок, анимация перехода уходят сами), потом один безопасный
    BACK, и только если экран всё ещё чужой — стоп со скрином и звуком.
    Ложная остановка дешевле пропуска, но и глохнуть на каждом баннере
    нельзя — отсюда две ступени.

    Отдельная ветка у базы: туда легко попасть случайным тапом, а выход —
    одна кнопка «Мир». Будить человека из-за этого незачем.

    Капчи и проверки сторож НЕ проходит: он для того и сделан, чтобы
    остановиться и позвать человека."""

    def __init__(self, driver, vision, cfg, log=print, sleep=time.sleep,
                 now=time.time, save=None, beep=None, human=None, cancel=None):
        self.driver = driver
        self.vision = vision
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        self.now = now
        self.human = human
        # сторож ждёт 12 с и жмёт BACK — после Стопа не нужно ни то, ни другое
        self.cancel = cancel if cancel is not None else Cancel()
        self._save = save if save is not None else _save_frame
        self._beep = beep if beep is not None else _beep

    def check(self):
        """'ok' — работаем; 'recovered' — экран снова знаком, начать итерацию
        заново; 'stop' — незнакомый экран, дальше только человек."""
        if not self.cfg.watchdog_enabled or self.cancel.stopped():
            return 'ok'
        screen = self.vision.classify_screen(self.driver.screenshot())
        if screen == 'base_view':
            return self._leave_base()
        if screen != 'unknown':
            return 'ok'

        # 1) ждём БЕЗ тапов: transient-экраны уходят сами
        for i in range(self.cfg.watchdog_wait_rounds):
            self.log(f"[сторож] незнакомый экран, жду "
                     f"({i + 1}/{self.cfg.watchdog_wait_rounds})")
            self.sleep(self.cfg.watchdog_wait_s)
            if self.cancel.stopped():
                return 'ok'
            screen = self.vision.classify_screen(self.driver.screenshot())
            if screen != 'unknown':
                self.log(f"[сторож] экран вернулся: {screen}")
                return 'recovered'

        # 2) один безопасный BACK
        self.log("[сторож] экран не ушёл сам -> BACK")
        safe_back(self.driver, self.vision, self.cfg, log=self.log,
                  sleep=self.sleep, human=self.human)
        self.sleep(self.cfg.watchdog_back_wait_s)
        img = self.driver.screenshot()
        screen = self.vision.classify_screen(img)
        if screen != 'unknown':
            self.log(f"[сторож] после BACK экран знаком: {screen}")
            return 'recovered'

        # 3) тревога
        return self._alarm(img)

    def _leave_base(self):
        """Из базы на карту мира кнопкой «Мир» (правый нижний угол).

        Это не аномалия и не повод будить человека: в базу легко попасть
        случайным тапом, а выход из неё — одна кнопка. Но если после
        world_button_attempts попыток мы всё ещё в базе, значит тапаем не
        туда — тогда обычная тревога."""
        for i in range(self.cfg.world_button_attempts):
            if self.cancel.stopped():
                return 'ok'
            self.log(f"[сторож] мы в базе -> кнопка «Мир» "
                     f"({i + 1}/{self.cfg.world_button_attempts})")
            img = self.driver.screenshot()
            pos = self.vision.find_button(img, "world_button")
            self.driver.tap(pos if pos is not None
                            else self.cfg.tap_box("world_button", self.cfg.world_button_xy))
            self.sleep(self.cfg.watchdog_back_wait_s)
            img = self.driver.screenshot()
            if self.vision.classify_screen(img) != 'base_view':
                self.log("[сторож] вернулись из базы на карту")
                return 'recovered'
        return self._alarm(self.driver.screenshot())

    def _alarm(self, img):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now()))
        path = os.path.join(self.cfg.watchdog_dir, f"anomaly-{stamp}.png")
        try:
            self._save(path, img)
            self.log(f"[сторож] кадр сохранён: {path}")
        except Exception as exc:      # диск/права не должны ронять бота
            self.log(f"[сторож] не смог сохранить кадр: {exc}")
        if self.cfg.watchdog_beep:
            self._beep()
        if self.cfg.watchdog_action == 'stop':
            self.log("[сторож] СТОП: экран не опознан. Разберись глазами "
                     "и запусти снова.")
            return 'stop'
        self.log("[сторож] режим наблюдения: кадр записан, работаю дальше.")
        return 'ok'

def _save_frame(path, img):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, img)

def _beep():
    """Позвать человека. Звук не должен ронять бота, поэтому любые
    ошибки (не Windows, нет звуковой карты) глотаем молча."""
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(880, 250)
    except Exception:
        pass
