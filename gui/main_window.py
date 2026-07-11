"""
gui/main_window.py

Tkinter forma:
  - dva numericka polja: "Od broja racuna" (broj1), "Do broja racuna" (broj2)
  - kontrola broj1 <= broj2
  - gumb "Pokreni uvoz"
  - log prozor koji uzivo prikazuje napredak (racun po racun)

Uvoz se izvrsava u pozadinskoj niti (threading.Thread) da GUI ne zamrzne
tijekom uvoza. Komunikacija iz worker niti prema GUI niti ide preko
queue.Queue, cita se periodicki preko self.after(...) - standardni i siguran
nacin za azuriranje Tkinter sucelja iz druge niti.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from config import ConfigError, load_config
import import_engine


class ImportApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Uvoz racuna - Clipper DBF -> Firebird")
        self.geometry("720x520")

        try:
            self.cfg = load_config("param.ini")
        except ConfigError as e:
            messagebox.showerror("Greska konfiguracije", str(e))
            self.destroy()
            return

        self._log_queue: queue.Queue = queue.Queue()
        self._worker_thread: threading.Thread | None = None

        self._build_ui()
        self.after(100, self._drain_log_queue)

    # ------------------------------------------------------------------
    # Izgradnja sucelja
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        frm = tk.Frame(self, padx=10, pady=10)
        frm.pack(fill=tk.X)

        tk.Label(frm, text="Od broja racuna:").grid(row=0, column=0, sticky="w")
        self.broj1_var = tk.StringVar()
        tk.Entry(frm, textvariable=self.broj1_var, width=12).grid(row=0, column=1, padx=5)

        tk.Label(frm, text="Do broja racuna:").grid(row=0, column=2, sticky="w", padx=(15, 0))
        self.broj2_var = tk.StringVar()
        tk.Entry(frm, textvariable=self.broj2_var, width=12).grid(row=0, column=3, padx=5)

        self.start_btn = tk.Button(frm, text="Pokreni uvoz", command=self._on_start, width=14)
        self.start_btn.grid(row=0, column=4, padx=(15, 0))

        self.status_var = tk.StringVar(value="Spremno.")
        tk.Label(self, textvariable=self.status_var, anchor="w", padx=10, fg="#333").pack(fill=tk.X)

        self.log_text = scrolledtext.ScrolledText(self, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def _append_log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Pokretanje uvoza
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        broj1_text = self.broj1_var.get().strip()
        broj2_text = self.broj2_var.get().strip()

        if not broj1_text.isdigit() or not broj2_text.isdigit():
            messagebox.showerror("Greska", "Oba polja moraju biti cijeli brojevi (npr. 100).")
            return

        broj1, broj2 = int(broj1_text), int(broj2_text)
        if broj1 > broj2:
            messagebox.showerror("Greska", "'Od broja racuna' mora biti manji ili jednak 'Do broja racuna'.")
            return

        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showwarning("Upozorenje", "Uvoz je vec u tijeku - pricekajte da zavrsi.")
            return

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

        self.start_btn.configure(state="disabled")
        self.status_var.set(f"Uvoz u tijeku: racuni {broj1}-{broj2}...")

        self._worker_thread = threading.Thread(
            target=self._run_import_worker, args=(broj1, broj2), daemon=True
        )
        self._worker_thread.start()

    def _run_import_worker(self, broj1: int, broj2: int) -> None:
        """Pokrece se u pozadinskoj niti - NE dira Tkinter widgete direktno, samo salje poruke u queue."""

        def log_callback(msg: str) -> None:
            self._log_queue.put(msg)

        try:
            stats = import_engine.run_import(self.cfg, broj1, broj2, log_callback=log_callback)
            self._log_queue.put(("__DONE__", stats))
        except import_engine.ImportAbortError as e:
            self._log_queue.put(("__ABORTED__", str(e)))
        except Exception as e:
            self._log_queue.put(("__ERROR__", f"{type(e).__name__}: {e}"))

    # ------------------------------------------------------------------
    # Citanje poruka iz worker niti (poziva se periodicki iz GUI niti)
    # ------------------------------------------------------------------

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self._log_queue.get_nowait()
                if isinstance(item, tuple):
                    kind = item[0]
                    if kind == "__DONE__":
                        stats = item[1]
                        self.status_var.set(
                            f"Gotovo. Uvezeno: {stats.uvezeno}, "
                            f"preskoceno (vec postoje): {stats.preskoceno_postojeci}, "
                            f"greske: {stats.gresaka}"
                        )
                        self.start_btn.configure(state="normal")
                    elif kind == "__ABORTED__":
                        self._append_log(f"IMPORT PREKINUT: {item[1]}")
                        self.status_var.set("Import prekinut zbog greske (vidi log).")
                        messagebox.showerror("Import prekinut", item[1])
                        self.start_btn.configure(state="normal")
                    elif kind == "__ERROR__":
                        self._append_log(f"NEOCEKIVANA GRESKA: {item[1]}")
                        self.status_var.set("Neocekivana greska (vidi log).")
                        messagebox.showerror("Greska", item[1])
                        self.start_btn.configure(state="normal")
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)


def launch_app() -> None:
    app = ImportApp()
    app.mainloop()