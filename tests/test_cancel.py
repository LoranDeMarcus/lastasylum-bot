import threading
import time
from src.cancel import Cancel

def test_sleep_returns_immediately_when_already_stopped():
    c = Cancel()
    c.set()
    t0 = time.perf_counter()
    c.sleep(5.0)
    assert time.perf_counter() - t0 < 0.5

def test_sleep_waits_full_time_when_not_stopped():
    """Пауза не укорачивается сама по себе: принцип «только вверх»."""
    c = Cancel()
    t0 = time.perf_counter()
    c.sleep(0.2)
    assert time.perf_counter() - t0 >= 0.18

def test_sleep_wakes_up_when_stopped_from_another_thread():
    """Главный сценарий: Стоп нажат, пока бот спит в паузе."""
    c = Cancel()
    threading.Timer(0.1, c.set).start()
    t0 = time.perf_counter()
    c.sleep(5.0)
    assert time.perf_counter() - t0 < 1.0
    assert c.is_set()

def test_injected_sleep_is_used_instead_of_waiting():
    """Тестовый шов: фейк фиксирует длительность и не спит."""
    slept = []
    c = Cancel(sleep=slept.append)
    c.sleep(0.8)
    assert slept == [0.8]

def test_duck_types_threading_event():
    """engine.run(cancel) принимает его как обычный stop_event."""
    c = Cancel()
    assert c.is_set() is False and c.stopped() is False
    c.set()
    assert c.is_set() is True and c.stopped() is True
    c.clear()
    assert c.is_set() is False

def test_wraps_given_event():
    """BotController отдаёт один объект и фабрике, и потоку движка."""
    ev = threading.Event()
    c = Cancel(ev)
    ev.set()
    assert c.is_set()
