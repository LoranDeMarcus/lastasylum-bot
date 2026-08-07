# src/cancel.py
import threading

class Cancel:
    """Кооперативная отмена: спим так, чтобы можно было проснуться.

    Кнопка Стоп раньше «не срабатывала сразу»: stop_event проверялся только
    между итерациями движка, а итерация спит до ~20 с. Здесь сон и признак
    остановки — ОДИН объект, поэтому Стоп будит бота из любой паузы.

    Утиная совместимость с threading.Event (is_set/set/clear): engine.run
    принимает Cancel как обычный stop_event, а тесты по-прежнему могут
    передать настоящий Event."""

    def __init__(self, event=None, sleep=None):
        self._event = event if event is not None else threading.Event()
        # тесты подсовывают свой sleep: он фиксирует длительность и не спит
        self._sleep = sleep

    def is_set(self):
        return self._event.is_set()

    def stopped(self):
        """Синоним is_set — читается на месте в точках проверки флоу."""
        return self._event.is_set()

    def set(self):
        self._event.set()

    def clear(self):
        self._event.clear()

    def sleep(self, seconds):
        """Спит seconds секунд, но просыпается сразу при Стопе.

        Принцип «паузы только вверх» не нарушается: Event.wait возвращается
        раньше срока лишь по set(), то есть когда следующего действия уже
        не будет."""
        if self._sleep is not None:
            self._sleep(seconds)
            return
        self._event.wait(seconds)
