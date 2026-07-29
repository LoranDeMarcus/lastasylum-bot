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

def run_gui(controller, log_queue=None):
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

    btns = tk.Frame(root); btns.pack(pady=6)
    tk.Button(btns, text="Start", width=12,
              command=controller.start).pack(side="left", padx=6)
    tk.Button(btns, text="Stop", width=12,
              command=controller.stop).pack(side="left", padx=6)
    root.mainloop()
