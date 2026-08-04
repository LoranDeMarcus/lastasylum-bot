# src/gui.py
import queue
import threading

class BotController:
    def __init__(self, engine_factory):
        self._factory = engine_factory
        self._thread = None
        self._stop = threading.Event()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return
        self._stop.clear()
        engine = self._factory()
        self._thread = threading.Thread(target=engine.run, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

def apply_flask_count(cfg, raw):
    """Применить введённый в GUI текущий остаток склянок. Его приходится
    задавать руками: в окне энергии «В наличии: N» перекрыт счётчиком
    количества и не читается, поэтому бот ведёт остаток локально, вычитая
    реально потраченное. 0 = «не знаю», тогда порог не ограничивает.
    Мусорный/отрицательный ввод игнорируем."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return cfg.flask_count_start
    if n < 0:
        return cfg.flask_count_start
    cfg.flask_count_start = n
    return n

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
        row = tk.Frame(root); row.pack(pady=(0, 2))
        tk.Label(row, text="Склянок сейчас:").pack(side="left", padx=(0, 4))
        count_var = tk.StringVar(value=str(cfg.flask_count_start))
        tk.Entry(row, width=7, textvariable=count_var).pack(side="left", padx=(0, 10))
        tk.Label(row, text="Мин. остаток:").pack(side="left", padx=(0, 4))
        thr_var = tk.StringVar(value=str(cfg.flask_stop_threshold))
        tk.Entry(row, width=7, textvariable=thr_var).pack(side="left")

        def apply_settings():
            count_var.set(str(apply_flask_count(cfg, count_var.get())))
            thr_var.set(str(apply_flask_threshold(cfg, thr_var.get())))
            if log_queue is not None:
                log_queue.put(f"Склянок: {cfg.flask_count_start}, "
                              f"не тратить ниже {cfg.flask_stop_threshold}")

        tk.Button(row, text="Применить", command=apply_settings).pack(side="left", padx=6)

    btns = tk.Frame(root); btns.pack(pady=6)
    tk.Button(btns, text="Start", width=12,
              command=controller.start).pack(side="left", padx=6)
    tk.Button(btns, text="Stop", width=12,
              command=controller.stop).pack(side="left", padx=6)
    root.mainloop()
