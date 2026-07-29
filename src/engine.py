# src/engine.py
import os
import time
import traceback
from src.models import GameState
from src.decide import decide

class BotEngine:
    def __init__(self, driver, vision, actions, cfg, log=print, sleep=time.sleep):
        self.driver = driver
        self.vision = vision
        self.actions = actions
        self.cfg = cfg
        self.log = log
        self.sleep = sleep
        self.flasks = None

    def start(self):
        self.flasks = self.actions.flasks_left()
        self.log(f"Старт. Склянок: {self.flasks}")

    def read_state(self):
        img = self.driver.screenshot()
        energy = self.vision.read_energy(img)
        deployed = self.vision.read_deployed(img)
        targets = self.vision.find_targets(img)
        return GameState(
            flasks=self.flasks if self.flasks is not None else 10**9,
            energy=energy if energy is not None else 0,
            deployed=deployed if deployed is not None else 0,
            targets=targets, screen_w=self.cfg.screen_w, screen_h=self.cfg.screen_h,
        )

    def one_iteration(self):
        state = self.read_state()
        action = decide(state, self.cfg)
        if action.type == 'stop':
            self.log("Стоп: склянок меньше порога.")
        elif action.type == 'refill':
            self.flasks = self.actions.refill_energy()
            self.log(f"Рефилл. Склянок осталось: {self.flasks}")
        elif action.type == 'wait':
            self.actions.close_popups()
            self.sleep(2.0)
        elif action.type == 'assault_boss':
            self.log(f"Штурм босса ур.{action.target.level}")
            self.actions.assault_boss(action.target)
        elif action.type == 'attack_mob':
            self.log(f"Атака моба ур.{action.target.level}")
            self.actions.attack_mob(action.target)
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
            if action.type == 'stop':
                return 'stop'
            self.sleep(0.5)
