# src/app.py
import queue
from config import Config
from src.driver import AdbDriver
from src.numbers import TesseractReader   # или TemplateReader — выбрать на калибровке
from src.vision import Vision
from src.actions import Actions
from src.engine import BotEngine
from src.gui import BotController, run_gui

def main():
    cfg = Config()
    log_q = queue.Queue()

    def make_engine():
        driver = AdbDriver(cfg)
        reader = TesseractReader(cfg)
        vision = Vision(cfg, reader)
        actions = Actions(driver, vision, cfg)
        return BotEngine(driver, vision, actions, cfg, log=log_q.put)

    controller = BotController(make_engine)
    run_gui(controller, log_q)

if __name__ == "__main__":
    main()
