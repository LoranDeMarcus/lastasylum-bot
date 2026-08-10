# src/app.py
import queue
from config import Config
from src.driver import AdbDriver
from src.numbers import TemplateReader   # шаблоны цифр (без внешних зависимостей)
from src.vision import Vision
from src.actions import Actions
from src.corruption import CorruptionActions
from src.join import JoinActions
from src.engine import BotEngine
from src.human import Human
from src.watchdog import Watchdog
from src.gui import BotController, run_gui

def main():
    cfg = Config()
    log_q = queue.Queue()

    def make_engine(cancel):
        # Все паузы идут через cancel.sleep: тогда Стоп будит бота из любой
        # из них, а не только между итерациями движка.
        human = Human(cfg, sleep=cancel.sleep)
        driver = AdbDriver(cfg, human=human)
        reader = TemplateReader(cfg)
        vision = Vision(cfg, reader)
        actions = Actions(driver, vision, cfg, log=log_q.put, sleep=cancel.sleep,
                          human=human, cancel=cancel)
        corruption = CorruptionActions(driver, vision, actions, cfg, log=log_q.put,
                                       sleep=cancel.sleep, human=human, cancel=cancel)
        join = JoinActions(driver, vision, actions, cfg, log=log_q.put,
                           sleep=cancel.sleep, human=human, cancel=cancel)
        # sleep через cancel: иначе сторож проспит свои 12 с ожидания
        # непрерываемым sleep и кнопка Стоп снова начнёт «залипать»
        watchdog = Watchdog(driver, vision, cfg, log=log_q.put,
                            sleep=cancel.sleep, human=human, cancel=cancel)
        return BotEngine(driver, vision, actions, cfg, log=log_q.put,
                         sleep=cancel.sleep, corruption=corruption, join=join,
                         human=human, cancel=cancel, watchdog=watchdog)

    controller = BotController(make_engine)
    run_gui(controller, log_q, cfg)

if __name__ == "__main__":
    main()
