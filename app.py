"""Kleine Oberfläche für das Whatnot-Rechnungstool.

Login läuft in einem separaten, einmalig manuell eingeloggten Chrome-Profil
(siehe setup_login.py). Danach hier Show auswählen und auf Start klicken.

Playwright-Objekte dürfen nur auf dem Thread verwendet werden, der sie
erzeugt hat. Deshalb läuft die komplette Browser-Steuerung in genau einem
Hintergrund-Thread, der Befehle sequenziell aus einer Queue abarbeitet;
Tkinter (Hauptthread) kommuniziert nur über Queues mit ihm.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

from playwright.sync_api import sync_playwright

import config
import whatnot_automation as wa


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Whatnot Rechnungstool")
        root.geometry("980x520")
        root.minsize(900, 400)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.result_queue: queue.Queue[tuple] = queue.Queue()
        self.command_queue: queue.Queue[dict] = queue.Queue()
        self.shows_by_label: dict[str, str] = {}
        self.pause_event = threading.Event()
        self.pause_event.set()  # gesetzt = läuft, gelöscht = pausiert

        top = ttk.Frame(root, padding=(10, 10, 10, 0))
        top.pack(fill=tk.X)

        ttk.Label(top, text="Show:").pack(side=tk.LEFT)
        self.show_var = tk.StringVar()
        self.show_combo = ttk.Combobox(top, textvariable=self.show_var, width=50, state="disabled")
        self.show_combo.pack(side=tk.LEFT, padx=8)

        self.start_btn = ttk.Button(top, text="Start", command=self.on_start, state="disabled")
        self.start_btn.pack(side=tk.LEFT, padx=8)

        self.reload_btn = ttk.Button(top, text="Shows neu laden", command=self.on_reload, state="disabled")
        self.reload_btn.pack(side=tk.LEFT)

        self.stop_btn = ttk.Button(top, text="Stopp", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.continue_btn = ttk.Button(top, text="Fortsetzen", command=self.on_continue, state="disabled")
        self.continue_btn.pack(side=tk.LEFT, padx=8)

        ttk.Label(top, text="MwSt %:").pack(side=tk.LEFT, padx=(8, 0))
        self.vat_var = tk.StringVar(value="0")
        self.vat_entry = ttk.Entry(top, textvariable=self.vat_var, width=5)
        self.vat_entry.pack(side=tk.LEFT, padx=4)

        second_row = ttk.Frame(root, padding=(10, 6, 10, 0))
        second_row.pack(fill=tk.X)

        self.dry_run_var = tk.BooleanVar(value=True)
        self.dry_run_check = ttk.Checkbutton(
            second_row, text="Testlauf (nichts wird wirklich erstellt)", variable=self.dry_run_var
        )
        self.dry_run_check.pack(side=tk.LEFT)

        self.all_shows_var = tk.BooleanVar(value=False)
        self.all_shows_check = ttk.Checkbutton(
            second_row,
            text="Alle Sendungen (alle Shows, zum Testen von >50 Einträgen)",
            variable=self.all_shows_var,
            command=self.on_toggle_all_shows,
        )
        self.all_shows_check.pack(side=tk.LEFT, padx=12)

        ttk.Label(second_row, text="Sendungen pro Seite:").pack(side=tk.LEFT, padx=(12, 4))
        self.page_size_var = tk.StringVar(value="250")
        self.page_size_combo = ttk.Combobox(
            second_row, textvariable=self.page_size_var, width=5, state="readonly",
            values=["20", "50", "100", "250"],
        )
        self.page_size_combo.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Starte Browser ...")
        ttk.Label(root, textvariable=self.status_var, padding=(10, 0)).pack(fill=tk.X)

        self.progress = ttk.Progressbar(root, mode="determinate")
        self.progress.pack(fill=tk.X, padx=10, pady=6)

        self.log_text = scrolledtext.ScrolledText(root, state="disabled", wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll_queues)

        threading.Thread(target=self.worker_main, daemon=True).start()

    def log(self, message: str) -> None:
        self.log_queue.put(message)

    def poll_queues(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass

        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                self._handle_result(kind, payload)
        except queue.Empty:
            pass

        self.root.after(100, self.poll_queues)

    def _handle_result(self, kind: str, payload) -> None:
        if kind == "ready":
            self.status_var.set("Eingeloggt. Lade Shows ...")
        elif kind == "shows":
            self.shows_by_label = {s.label: s.raw_text for s in payload}
            self.show_combo["values"] = list(self.shows_by_label.keys())
            if payload:
                self.show_combo.current(0)
            self.show_combo.configure(state="readonly")
            self.reload_btn.configure(state="normal")
            self.start_btn.configure(state="normal")
            self.status_var.set(f"{len(payload)} Shows geladen. Bereit.")
        elif kind == "shows_error":
            self.reload_btn.configure(state="normal")
            self.status_var.set("Fehler beim Laden der Shows.")
        elif kind == "progress":
            done, total = payload
            if str(self.progress["mode"]) == "determinate":
                self.progress.configure(value=done, maximum=max(total, 1))
            self.status_var.set(f"Verarbeite ... ({done} Sendungen bisher gesehen)")
        elif kind == "run_done":
            self.log(
                "Fertig. Erstellt: {erstellt}, bereits vorhanden: "
                "{uebersprungen_bereits}, ohne Rechnung (0€): "
                "{uebersprungen_0eur}, noch bei Whatnot in Bearbeitung: "
                "{in_bearbeitung}, Fehler: {fehler}".format(**payload)
            )
            if payload.get("in_bearbeitung"):
                self.log(
                    f"  Hinweis: {payload['in_bearbeitung']} Rechnung(en) waren bei Whatnot "
                    "noch nicht rechtzeitig fertig. Tool in ein paar Minuten erneut "
                    "laufen lassen, dann werden diese nur noch heruntergeladen."
                )
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.status_var.set("Fertig.")
            self.start_btn.configure(state="normal")
            self.reload_btn.configure(state="normal")
            self.all_shows_check.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.continue_btn.configure(state="disabled")
            self.on_toggle_all_shows()
        elif kind == "run_error":
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.status_var.set("Fehler.")
            self.start_btn.configure(state="normal")
            self.reload_btn.configure(state="normal")
            self.all_shows_check.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.continue_btn.configure(state="disabled")
            self.on_toggle_all_shows()
        elif kind == "init_error":
            self.status_var.set("Fehler beim Start des Browsers.")

    def on_toggle_all_shows(self) -> None:
        if self.all_shows_var.get():
            self.show_combo.configure(state="disabled")
        else:
            self.show_combo.configure(state="readonly")

    def on_reload(self) -> None:
        self.reload_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.command_queue.put({"type": "reload_shows"})

    def on_start(self) -> None:
        all_shows = self.all_shows_var.get()
        label = self.show_var.get()
        raw_text = self.shows_by_label.get(label)
        if not all_shows and not raw_text:
            return
        try:
            vat_rate = int(self.vat_var.get())
        except ValueError:
            self.log(f"Ungültiger MwSt-Satz: {self.vat_var.get()!r} (bitte eine Zahl eingeben).")
            return
        self.start_btn.configure(state="disabled")
        self.reload_btn.configure(state="disabled")
        self.show_combo.configure(state="disabled")
        self.all_shows_check.configure(state="disabled")
        self.pause_event.set()
        self.stop_btn.configure(state="normal")
        self.continue_btn.configure(state="disabled")
        if all_shows:
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
        else:
            self.progress.configure(mode="determinate", value=0, maximum=100)
        dry_run = self.dry_run_var.get()
        mode = "TESTLAUF" if dry_run else "ECHTER LAUF"
        target = "ALLE SENDUNGEN" if all_shows else label
        self.log(f"Starte Verarbeitung ({mode}, {vat_rate}% MwSt): {target}")
        self.command_queue.put(
            {
                "type": "start",
                "show_raw_text": raw_text,
                "dry_run": dry_run,
                "vat_rate": vat_rate,
                "all_shows": all_shows,
                "page_size": int(self.page_size_var.get()),
            }
        )

    def on_stop(self) -> None:
        self.pause_event.clear()
        self.log("Stopp angefordert – pausiert nach der aktuellen Sendung ...")
        self.stop_btn.configure(state="disabled")
        self.continue_btn.configure(state="normal")

    def on_continue(self) -> None:
        self.pause_event.set()
        self.log("Fortsetzen angefordert ...")
        self.stop_btn.configure(state="normal")
        self.continue_btn.configure(state="disabled")

    def on_close(self) -> None:
        self.pause_event.set()
        self.command_queue.put({"type": "quit"})
        self.root.after(300, self.root.destroy)

    # --- läuft komplett im eigenen Hintergrund-Thread ---

    def worker_main(self) -> None:
        try:
            with sync_playwright() as playwright:
                context = wa.launch_context(playwright)
                page = context.new_page()
                wa.ensure_logged_in(page, log=self.log)
                self.result_queue.put(("ready", None))
                self._reload_shows(page)

                while True:
                    cmd = self.command_queue.get()
                    if cmd["type"] == "quit":
                        break
                    elif cmd["type"] == "reload_shows":
                        self._reload_shows(page)
                    elif cmd["type"] == "start":
                        self._run(
                            context, page, cmd["show_raw_text"], cmd["dry_run"],
                            cmd["vat_rate"], cmd["all_shows"], cmd["page_size"],
                        )

                context.close()
        except Exception as exc:  # noqa: BLE001
            self.log(f"Browser-Fehler: {exc}")
            self.result_queue.put(("init_error", None))

    def _reload_shows(self, page) -> None:
        try:
            shows = wa.list_shows(page)
            self.result_queue.put(("shows", shows))
        except Exception as exc:  # noqa: BLE001
            self.log(f"Fehler beim Laden der Shows: {exc}")
            self.result_queue.put(("shows_error", None))

    def _run(
        self, context, page, show_raw_text: str | None, dry_run: bool,
        vat_rate: int, all_shows: bool, page_size: int,
    ) -> None:
        try:
            def on_progress(done: int, total: int) -> None:
                self.result_queue.put(("progress", (done, total)))

            stats = wa.process_show(
                context, page, show_raw_text, vat_rate,
                log=self.log, on_progress=on_progress, dry_run=dry_run,
                all_shows=all_shows, page_size=page_size,
                pause_event=self.pause_event,
            )
            self.result_queue.put(("run_done", stats))
        except Exception as exc:  # noqa: BLE001
            self.log(f"Abgebrochen wegen Fehler: {exc}")
            self.result_queue.put(("run_error", None))


def main() -> None:
    config.OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
