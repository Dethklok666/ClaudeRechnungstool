"""Automatisiert die Erstellung von MwSt-Rechnungen im Whatnot Verkäufer-Hub.

Nutzt die auf whatnot.com eingebaute "Rechnung mit Mwst. erstellen"-Funktion
(Sendungen-Liste) und lädt die erzeugten PDFs herunter. Der MwSt-Satz wird
pro Lauf manuell in der Oberfläche vorgegeben (nicht automatisch anhand
irgendeines Datums bestimmt).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, TimeoutError as PWTimeout

import config

_MONTHS = {
    "jan": 1, "feb": 2, "märz": 3, "mar": 3, "apr": 4, "mai": 5,
    "juni": 6, "jun": 6, "juli": 7, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "okt": 10, "nov": 11, "dez": 12,
}

_DATE_RE = re.compile(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\.?\s*(\d{4})")
_BESTELLUNG_RE = re.compile(r"Bestellung\s*Nr\.?\s*(\d+)")
_BESTELLNR_PANEL_RE = re.compile(r"Bestellnr\.?\s*(\d+)")


class AutomationError(Exception):
    pass


class InvoicePendingError(AutomationError):
    """Die Rechnung wurde gesendet, aber Whatnot hat sie nicht rechtzeitig
    fertiggestellt. Kein echter Fehler – beim nächsten Lauf erscheint die
    Sendung als bereits fakturiert und die PDF kann einfach heruntergeladen
    werden."""


@dataclass
class ShowOption:
    label: str  # Anzeigetext, Datum zuerst
    raw_text: str  # exakter Original-Text, zum Wiederfinden im Dropdown


@dataclass
class ShipmentRow:
    row_index: int
    empfaenger: str
    bestelldatum_text: str
    wert_text: str
    wert: float


@dataclass
class InvoiceResult:
    filed_path: Path
    bestellnrs: list[str] = field(default_factory=list)


def parse_german_date(text: str) -> date:
    match = _DATE_RE.search(text)
    if not match:
        raise AutomationError(f"Konnte Datum nicht lesen: {text!r}")
    day, month_name, year = match.groups()
    key = month_name.lower().rstrip(".")
    month = _MONTHS.get(key)
    if month is None:
        raise AutomationError(f"Unbekannter Monatsname: {month_name!r}")
    return date(int(year), month, int(day))


def parse_euro(text: str) -> float:
    cleaned = text.replace("€", "").replace("\xa0", " ").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def launch_context(playwright: Playwright, headless: bool = False) -> BrowserContext:
    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # channel="chrome" nutzt das im System installierte Google Chrome statt
    # des von Playwright heruntergeladenen Chromium-Pakets (das auf diesem
    # Rechner wegen einer ungültigen Side-by-Side-Assembly nicht startet).
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        channel="chrome",
        headless=headless,
        locale="de-DE",
        viewport={"width": 1400, "height": 1000},
    )
    return context


def ensure_logged_in(page: Page, log=print, timeout_seconds: int = 300) -> None:
    page.goto(config.WHATNOT_SHIPMENTS_URL)
    if "/login" not in page.url:
        return
    log("Bitte im geöffneten Browserfenster manuell bei Whatnot einloggen ...")
    page.wait_for_url(lambda url: "/login" not in url, timeout=timeout_seconds * 1000)
    log("Login erkannt.")


def _open_show_filter_menu(page: Page):
    trigger = page.locator('button[id^="radix-"]').nth(0)
    trigger.wait_for(state="visible", timeout=15000)
    options = page.get_by_role("menuitemradio")
    for attempt in range(3):
        trigger.click()
        try:
            options.first.wait_for(state="visible", timeout=5000)
            # Die ersten beiden Einträge ("Alle Sendungen", "Profilshop")
            # erscheinen sofort, die eigentlichen Shows werden kurz danach
            # nachgeladen. Deshalb warten, bis mehr als 2 Einträge da sind
            # und sich die Anzahl nicht mehr ändert.
            previous_count = -1
            for _ in range(20):
                page.wait_for_timeout(200)
                current_count = options.count()
                if current_count > 2 and current_count == previous_count:
                    return options
                previous_count = current_count
            return options
        except PWTimeout:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
    raise AutomationError("Show-Filter-Menü öffnet sich nicht.")


def list_shows(page: Page) -> list[ShowOption]:
    page.goto(config.WHATNOT_SHIPMENTS_URL)
    options = _open_show_filter_menu(page)
    result = []
    for i in range(options.count()):
        text = options.nth(i).inner_text().strip()
        if not text or text.startswith("Alle Sendungen") or text == "Profilshop":
            continue
        lines = text.split("\n")
        title = lines[0] if lines else text
        date_part = lines[1] if len(lines) > 1 else ""
        label = f"{date_part} — {title}" if date_part else title
        # Nur Titel+Datum als Schlüssel nutzen: die dritte Zeile (Status wie
        # "Versand komplett") kann sich zwischendurch ändern und würde einen
        # exakten Textvergleich später zum Scheitern bringen.
        match_key = "\n".join(lines[:2]).strip()
        result.append(ShowOption(label=label, raw_text=match_key))
    page.keyboard.press("Escape")
    return result


def _select_all_status(page: Page) -> None:
    status_trigger = page.locator('button[id^="radix-"]').nth(1)
    alle_status_option = page.get_by_role("menuitemradio", name="Alle Status")
    for attempt in range(3):
        status_trigger.click()
        try:
            alle_status_option.wait_for(state="visible", timeout=5000)
            break
        except PWTimeout:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
    else:
        raise AutomationError("Status-Filter-Menü öffnet sich nicht.")
    alle_status_option.click()
    page.wait_for_timeout(500)


def apply_show_filter(page: Page, show_match_key: str) -> None:
    options = _open_show_filter_menu(page)
    seen = []
    for i in range(options.count()):
        text = options.nth(i).inner_text().strip()
        key = "\n".join(text.split("\n")[:2]).strip()
        seen.append(key)
        if key == show_match_key:
            options.nth(i).click()
            break
    else:
        page.keyboard.press("Escape")
        details = "\n".join(f"  {k!r}" for k in seen)
        raise AutomationError(
            f"Show nicht gefunden: {show_match_key!r}\nGefundene Optionen:\n{details}"
        )
    _select_all_status(page)


def apply_all_shows_filter(page: Page) -> None:
    options = _open_show_filter_menu(page)
    # Erster Eintrag im Dropdown ist immer "Alle Sendungen / Shows & Profilshop".
    options.first.click()
    _select_all_status(page)


def set_page_size(page: Page, size: int) -> None:
    toggle = page.locator('button[id*="toggle-button"]')
    if toggle.count() == 0:
        return
    toggle.first.click()
    option = page.get_by_role("option", name=f"{size} anzeigen", exact=True)
    try:
        option.wait_for(state="visible", timeout=3000)
        option.click()
        page.wait_for_timeout(500)
    except PWTimeout:
        page.keyboard.press("Escape")


def has_next_page(page: Page) -> bool:
    next_btn = page.locator('button:has(svg[aria-label="Nächste Seite"])')
    if next_btn.count() == 0:
        return False
    # Kurz warten und erneut prüfen: direkt nach dem Schließen des letzten
    # Sendungs-Panels kann der Button kurzzeitig noch im alten (deaktivierten)
    # Zustand sein, obwohl es tatsächlich noch weitere Seiten gibt.
    if next_btn.first.get_attribute("disabled") is not None:
        page.wait_for_timeout(800)
        if next_btn.first.get_attribute("disabled") is not None:
            return False
    return True


def go_to_next_page(page: Page) -> None:
    next_btn = page.locator('button:has(svg[aria-label="Nächste Seite"])')
    next_btn.first.click()
    page.wait_for_timeout(500)


def get_shipment_rows(page: Page) -> list[ShipmentRow]:
    rows = page.locator('tr[data-testid^="shipments-"]')
    empty_state = page.get_by_text("Es müssen keine Sendungen verschickt werden")
    # Nach dem Setzen der Filter (v.a. bei "Alle Sendungen" mit vielen
    # Einträgen) braucht die Tabelle spürbar Zeit zum Nachladen – warten, bis
    # entweder Zeilen erscheinen, der Leerzustand angezeigt wird, oder sich
    # die Zeilenanzahl über einen längeren Zeitraum nicht mehr ändert.
    previous_count = -1
    stable_checks = 0
    for _ in range(100):
        page.wait_for_timeout(300)
        current_count = rows.count()
        if empty_state.count() > 0:
            break
        if current_count > 0 and current_count == previous_count:
            stable_checks += 1
            if stable_checks >= 3:
                break
        else:
            stable_checks = 0
        previous_count = current_count

    result = []
    for i in range(rows.count()):
        cells = rows.nth(i).locator("td")
        # Direkt aus dem Link lesen statt über Zeilenumbrüche zu splitten:
        # je nach Fensterbreite steht "Erweitern" manchmal ohne Zeilenumbruch
        # (nur mit \xa0) direkt hinter dem Namen im selben Textblock.
        empfaenger_link = cells.nth(1).locator("a").first
        if empfaenger_link.count():
            empfaenger = empfaenger_link.inner_text().strip()
        else:
            empfaenger = cells.nth(1).inner_text().split("\n")[0].strip()
        bestelldatum_text = cells.nth(2).inner_text().strip()
        wert_text = cells.nth(4).inner_text().strip()
        result.append(
            ShipmentRow(
                row_index=i,
                empfaenger=empfaenger,
                bestelldatum_text=bestelldatum_text,
                wert_text=wert_text,
                wert=parse_euro(wert_text),
            )
        )
    return result


def open_row_panel(page: Page, row_index: int, expected_empfaenger: str) -> None:
    rows = page.locator('tr[data-testid^="shipments-"]')
    rows.nth(row_index).locator("td").nth(2).click()
    sidebar = page.locator('[data-testid="shipment-details-sidebar"]')
    sidebar.wait_for(timeout=15000)
    # Sicherstellen, dass der Panel-Inhalt wirklich zur angeklickten Zeile
    # gehört – kurz nach dem Öffnen kann noch der Inhalt der vorherigen
    # Sendung sichtbar sein, was sonst zu falsch zugeordneten Bestellnummern
    # führen würde.
    for _ in range(50):
        if expected_empfaenger in sidebar.inner_text():
            break
        page.wait_for_timeout(200)
    else:
        raise AutomationError(
            f"Sendungs-Panel zeigt nicht die erwartete Sendung von {expected_empfaenger!r}."
        )
    page.wait_for_timeout(200)


def close_row_panel(page: Page) -> None:
    close_btn = page.locator('[data-testid="shipment-details-sidebar"]').get_by_label("Schließen")
    if close_btn.count():
        close_btn.first.click()
    page.wait_for_timeout(200)


InvoiceState = str  # "not_invoiced" | "already_invoiced" | "no_invoice_possible"


def get_invoice_state(page: Page) -> InvoiceState:
    sidebar = page.locator('[data-testid="shipment-details-sidebar"]')
    if sidebar.get_by_text("Mehrwertsteuerrechnung erstellen", exact=True).count():
        return "not_invoiced"
    if sidebar.get_by_text("wurde dem Käufer zugestellt").count():
        return "already_invoiced"
    return "no_invoice_possible"


def create_and_download_invoice(
    page: Page,
    vat_rate: int,
    order_date: date,
    username: str,
    log=print,
    dry_run: bool = False,
) -> InvoiceResult | None:
    sidebar = page.locator('[data-testid="shipment-details-sidebar"]')
    sidebar.get_by_text("Mehrwertsteuerrechnung erstellen", exact=True).click()

    dialog_heading = page.get_by_text("Rechnung mit Mwst. erstellen", exact=True)
    dialog_heading.wait_for(timeout=10000)

    order_blocks = page.get_by_text(_BESTELLUNG_RE)
    block_count = order_blocks.count()
    if block_count == 0:
        raise AutomationError("Keine Bestellblöcke im Rechnungsdialog gefunden.")

    bestellnrs: list[str] = []

    for i in range(block_count):
        block_text = order_blocks.nth(i).inner_text()
        match = _BESTELLUNG_RE.search(block_text)
        bestellnr = match.group(1)
        bestellnrs.append(bestellnr)

        container = order_blocks.nth(i).locator(
            "xpath=ancestor::div[.//input[@placeholder='Artikelbeschreibung eingeben']][1]"
        )
        text_inputs = container.locator('input[type="text"]')
        vat_input = text_inputs.nth(1)
        if not vat_input.is_enabled():
            # Gratis-/Giveaway-Position (FGA/KGA) innerhalb einer gebündelten
            # Sendung: das MwSt-Feld ist absichtlich deaktiviert, da kein
            # Entgelt anfällt.
            log(f"  Bestellung {bestellnr}: Gratis-Artikel, kein MwSt-Feld – übersprungen.")
            continue
        vat_input.fill(str(vat_rate))
        log(f"  Bestellung {bestellnr}: {vat_rate}% MwSt")

    if vat_rate == 0:
        notes = page.get_by_placeholder(
            "Gib alle Hinweise zu dieser Rechnung ein, wie die Kennzeichnung als "
            "Export, die Anwendung eines Margensystems oder sonstige relevante "
            "Details."
        )
        existing = notes.input_value()
        if config.KLEINUNTERNEHMER_NOTE not in existing:
            notes.fill((existing + " " + config.KLEINUNTERNEHMER_NOTE).strip())

    if dry_run:
        log(f"  [TESTLAUF] würde Rechnung senden für Bestellung(en) {', '.join(bestellnrs)} – breche ab.")
        page.get_by_role("button", name="Abbrechen").click()
        return None

    page.get_by_role("button", name="Rechnung senden & herunterladen").click()
    confirm_btn = page.get_by_role("button", name="Bestätigen")
    confirm_btn.wait_for(timeout=10000)
    confirm_btn.click()

    # Bei großen Sammel-Sendungen (viele gebündelte Bestellungen) stellt
    # Whatnot die Rechnung manchmal asynchron fertig und zeigt sofort einen
    # Hinweis-Toast ("Rechnungserstellung gestartet ... in ein paar Minuten
    # noch einmal nachsehen"). Sobald dieser Hinweis auftaucht, sofort weiter
    # zur nächsten Sendung, statt auf den vollen Timeout zu warten.
    success_locator = page.get_by_text("wurde dem Käufer zugestellt")
    pending_locator = page.get_by_text("Rechnungserstellung gestartet")
    deadline_seconds = 30
    elapsed = 0.0
    interval = 0.3
    while elapsed < deadline_seconds:
        if success_locator.count() > 0:
            break
        if pending_locator.count() > 0:
            raise InvoicePendingError(
                "Rechnung wurde gesendet, Whatnot erstellt sie noch "
                "asynchron (Hinweis-Toast erschienen)."
            )
        page.wait_for_timeout(int(interval * 1000))
        elapsed += interval
    else:
        raise InvoicePendingError(
            "Rechnung wurde gesendet, Whatnot hat sie aber noch nicht "
            "rechtzeitig fertiggestellt."
        )

    with page.expect_download() as dl_info:
        sidebar.get_by_role("button", name="Rechnung herunterladen").click()
    download = dl_info.value

    filed_path = file_pdf(download, order_date, bestellnrs, username)
    return InvoiceResult(filed_path=filed_path, bestellnrs=bestellnrs)


def download_existing_invoice(
    page: Page, order_date: date, username: str, log=print
) -> InvoiceResult:
    """Lädt die PDF einer bereits fakturierten Sendung erneut herunter.

    Rein lesend (kein neuer Rechnungsversand) – daher auch im Testlauf sicher.
    Wird u.a. genutzt, um Dateien nachzuholen, deren Ablage in einem früheren
    Lauf fehlgeschlagen ist. Existiert die Datei schon lokal, wird nicht
    erneut heruntergeladen.
    """
    sidebar = page.locator('[data-testid="shipment-details-sidebar"]')
    matches = sidebar.get_by_text(_BESTELLNR_PANEL_RE)
    bestellnrs = []
    for i in range(matches.count()):
        m = _BESTELLNR_PANEL_RE.search(matches.nth(i).inner_text())
        if m:
            bestellnrs.append(m.group(1))
    if not bestellnrs:
        bestellnrs = ["unbekannt"]

    target_path = expected_pdf_path(order_date, bestellnrs, username)
    if target_path.exists():
        log(f"  bereits lokal abgelegt: {target_path}")
        return InvoiceResult(filed_path=target_path, bestellnrs=bestellnrs)

    with page.expect_download() as dl_info:
        sidebar.get_by_role("button", name="Rechnung herunterladen").click()
    download = dl_info.value

    filed_path = file_pdf(download, order_date, bestellnrs, username)
    return InvoiceResult(filed_path=filed_path, bestellnrs=bestellnrs)


_MAX_NR_PART_LENGTH = 80


def _build_nr_part(bestellnrs: list[str]) -> str:
    full = "+".join(bestellnrs)
    if len(full) <= _MAX_NR_PART_LENGTH or len(bestellnrs) <= 1:
        return full
    # Bei sehr vielen gebündelten Bestellungen wird der Dateiname sonst
    # länger als von Windows erlaubt (~255 Zeichen) – dann nur die erste
    # Bestellnr. plus Anzahl der weiteren angeben.
    return f"{bestellnrs[0]}+{len(bestellnrs) - 1}weitere"


def expected_pdf_path(order_date: date, bestellnrs: list[str], username: str) -> Path:
    year_dir = config.OUTPUT_BASE_DIR / f"{order_date.year}"
    month_dir = year_dir / f"{order_date.month:02d}"
    nr_part = _build_nr_part(bestellnrs)
    safe_username = re.sub(r"[^\w\-]", "_", username)
    filename = f"{order_date.isoformat()}_{nr_part}_{safe_username}.pdf"
    return month_dir / filename


def file_pdf(download, order_date: date, bestellnrs: list[str], username: str) -> Path:
    target_path = expected_pdf_path(order_date, bestellnrs, username)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(target_path))
    return target_path


def process_show(
    context: BrowserContext,
    page: Page,
    show_label: str | None,
    vat_rate: int,
    log=print,
    on_progress=None,
    dry_run: bool = False,
    all_shows: bool = False,
    page_size: int = 250,
    pause_event=None,
) -> dict:
    stats = {
        "erstellt": 0,
        "uebersprungen_bereits": 0,
        "uebersprungen_0eur": 0,
        "in_bearbeitung": 0,
        "fehler": 0,
    }

    def apply_filters():
        if all_shows:
            apply_all_shows_filter(page)
        else:
            apply_show_filter(page, show_label)
        set_page_size(page, page_size)

    def goto_page(target_page_num: int) -> None:
        page.goto(config.WHATNOT_SHIPMENTS_URL)
        apply_filters()
        for _ in range(target_page_num - 1):
            go_to_next_page(page)

    page_num = 1
    total_seen = 0
    goto_page(page_num)

    while True:
        rows = get_shipment_rows(page)
        log(f"Seite {page_num}: {len(rows)} Sendungen gefunden.")

        for row in rows:
            if pause_event is not None and not pause_event.is_set():
                log("Pausiert. Warte auf Fortsetzen ...")
                pause_event.wait()
                log("Fortgesetzt.")

            total_seen += 1
            if on_progress:
                on_progress(total_seen, total_seen)

            if row.wert <= 0:
                log(f"[{row.empfaenger}] 0,00 € – übersprungen (keine Rechnung möglich).")
                stats["uebersprungen_0eur"] += 1
                continue

            try:
                open_row_panel(page, row.row_index, row.empfaenger)
                state = get_invoice_state(page)

                order_date = parse_german_date(row.bestelldatum_text)

                if state == "already_invoiced":
                    log(f"[{row.empfaenger}] bereits fakturiert – lade Rechnung erneut herunter ...")
                    try:
                        result = download_existing_invoice(page, order_date, row.empfaenger, log)
                        log(f"[{row.empfaenger}] abgelegt: {result.filed_path}")
                    except (AutomationError, PWTimeout) as exc:
                        log(f"[{row.empfaenger}] Download fehlgeschlagen: {exc}")
                    stats["uebersprungen_bereits"] += 1
                elif state == "no_invoice_possible":
                    log(f"[{row.empfaenger}] keine Rechnungsoption verfügbar – übersprungen.")
                    stats["uebersprungen_0eur"] += 1
                else:
                    log(f"[{row.empfaenger}] erstelle Rechnung ...")
                    result = create_and_download_invoice(
                        page, vat_rate, order_date, row.empfaenger, log, dry_run=dry_run
                    )
                    if result is not None:
                        log(f"[{row.empfaenger}] abgelegt: {result.filed_path}")
                    stats["erstellt"] += 1

                close_row_panel(page)
            except InvoicePendingError:
                log(
                    f"[{row.empfaenger}] wird von Whatnot noch fertiggestellt – "
                    "kein Fehler, bitte das Tool in ein paar Minuten erneut "
                    "laufen lassen, dann wird die PDF nur noch heruntergeladen."
                )
                stats["in_bearbeitung"] += 1
                goto_page(page_num)
            except (AutomationError, PWTimeout) as exc:
                log(f"[{row.empfaenger}] FEHLER: {exc}")
                stats["fehler"] += 1
                # Zurück zur selben Seite navigieren, damit die restlichen
                # Zeilen dieser Seite weiterverarbeitet werden können.
                goto_page(page_num)

        if pause_event is not None and not pause_event.is_set():
            log("Pausiert. Warte auf Fortsetzen ...")
            pause_event.wait()
            log("Fortgesetzt.")

        if not has_next_page(page):
            log(f"Seite {page_num}: keine weitere Seite verfügbar – fertig.")
            break
        go_to_next_page(page)
        page_num += 1

    return stats
