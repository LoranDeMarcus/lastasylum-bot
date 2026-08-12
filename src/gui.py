# src/gui.py
import queue
import threading
from src.cancel import Cancel
from src.version import VERSION

# Заголовок окна — вынесен в константу, чтобы версия была видна человеку и
# проверялась тестом без запуска tkinter (run_gui импортирует его лениво).
GUI_TITLE = f"Last Asylum Bot {VERSION}"

class BotController:
    """Владелец отмены: один Cancel уходит и в фабрику (там на нём строятся
    все паузы), и в поток движка (там он обычный stop_event)."""

    def __init__(self, engine_factory):
        self._factory = engine_factory
        self._thread = None
        self._cancel = Cancel()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return
        self._cancel.clear()
        engine = self._factory(self._cancel)
        self._thread = threading.Thread(target=engine.run, args=(self._cancel,), daemon=True)
        self._thread.start()

    def stop(self):
        self._cancel.set()

def apply_flask_threshold(cfg, raw):
    """Применить введённый в GUI нижний порог остатка склянок: ниже него бот
    больше не тратит склянки на рефилл (и останавливается, когда энергии не
    хватает). Мусорный/отрицательный ввод игнорируем — остаётся прежнее
    значение, чтобы опечатка не отключила защиту. Возвращает действующее
    значение (его же кладём обратно в поле)."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return cfg.flask_stop_threshold
    if n < 0:
        return cfg.flask_stop_threshold
    cfg.flask_stop_threshold = n
    return n

def apply_strategy(cfg, value):
    """Режим бота из GUI. Неизвестное значение игнорируем: лучше остаться в
    прежнем режиме, чем уронить движок неизвестной веткой."""
    if value in ("corruption", "join", "thief"):
        cfg.strategy = value
    return cfg.strategy

def run_gui(controller, log_queue=None, cfg=None):
    import tkinter as tk
    root = tk.Tk()
    root.title(GUI_TITLE)
    log = tk.Text(root, height=18, width=60, state="disabled")
    log.pack(padx=8, pady=8)

    def append(msg):
        log.configure(state="normal")
        log.insert("end", msg + "\n")
        log.see("end")
        log.configure(state="disabled")

    if log_queue is not None:
        def poll():
            while True:
                try:
                    msg = log_queue.get_nowait()
                except queue.Empty:
                    break
                append(msg)
            root.after(200, poll)
        root.after(200, poll)

    if cfg is not None:
        # Текущий остаток склянок бот читает сам («В наличии: N» после первого
        # рефилла), руками задаётся только порог — это решение человека.
        row = tk.Frame(root); row.pack(pady=(0, 2))
        tk.Label(row, text="Мин. остаток склянок:").pack(side="left", padx=(0, 4))
        thr_var = tk.StringVar(value=str(cfg.flask_stop_threshold))
        tk.Entry(row, width=7, textvariable=thr_var).pack(side="left")

        def apply_settings():
            thr_var.set(str(apply_flask_threshold(cfg, thr_var.get())))
            if log_queue is not None:
                log_queue.put(f"Не тратить склянки ниже {cfg.flask_stop_threshold}")

        tk.Button(row, text="Применить", command=apply_settings).pack(side="left", padx=6)

        squad_row = tk.Frame(root); squad_row.pack(pady=(0, 2))
        fourth_var = tk.BooleanVar(value=cfg.use_fourth_squad)

        def toggle_fourth():
            # пишем в cfg сразу, без «Применить»: движок читает cfg каждую
            # итерацию, значит переключать можно не останавливая бота
            cfg.use_fourth_squad = bool(fourth_var.get())
            if log_queue is not None:
                log_queue.put(f"Отрядов бот занимает максимум: {cfg.squad_limit()}")

        tk.Checkbutton(squad_row, text="Отправлять 4-й отряд",
                       variable=fourth_var, command=toggle_fourth).pack(side="left")

        mode_row = tk.Frame(root); mode_row.pack(pady=(0, 2))
        mode_var = tk.StringVar(value=cfg.strategy)

        def apply_mode():
            # пишем в cfg сразу, без «Применить»: движок читает cfg каждую
            # итерацию, значит режим можно менять, не останавливая бота
            apply_strategy(cfg, mode_var.get())
            if log_queue is not None:
                names = {"corruption": "свой штурм", "join": "присоединяться к чужим",
                         "thief": "поиск вора"}
                log_queue.put(f"Режим: {names.get(cfg.strategy, cfg.strategy)}")

        tk.Label(mode_row, text="Режим:").pack(side="left", padx=(0, 4))
        tk.Radiobutton(mode_row, text="Свой штурм", value="corruption",
                       variable=mode_var, command=apply_mode).pack(side="left")
        tk.Radiobutton(mode_row, text="Присоединяться", value="join",
                       variable=mode_var, command=apply_mode).pack(side="left")
        tk.Radiobutton(mode_row, text="Поиск вора", value="thief",
                       variable=mode_var, command=apply_mode).pack(side="left")

    def request_stop():
        # без этой строки пауза до первой реакции выглядит как «кнопка не работает»
        controller.stop()
        if log_queue is not None:
            log_queue.put("Стоп запрошен — доигрываю текущий шаг.")

    btns = tk.Frame(root); btns.pack(pady=6)
    tk.Button(btns, text="Start", width=12,
              command=controller.start).pack(side="left", padx=6)
    tk.Button(btns, text="Stop", width=12,
              command=request_stop).pack(side="left", padx=6)
    root.mainloop()
