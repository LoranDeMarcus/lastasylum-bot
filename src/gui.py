# src/gui.py
import queue
import threading
from src.cancel import Cancel

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

def run_gui(controller, log_queue=None, cfg=None):
    import tkinter as tk
    root = tk.Tk()
    root.title("Last Asylum Bot")
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
