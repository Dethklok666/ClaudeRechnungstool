"""Konfiguration für das Whatnot-Rechnungstool."""

from pathlib import Path

# Hinweistext, der Rechnungen mit 0% MwSt automatisch hinzugefügt wird.
KLEINUNTERNEHMER_NOTE = (
    "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung)."
)

# Wo die fertigen Rechnungs-PDFs abgelegt werden (Unterordner Jahr/Monat werden
# automatisch angelegt). Path.home() statt festem Benutzernamen, damit das
# auf jedem Rechner funktioniert, auf dem dieser OneDrive-Ordner synchronisiert.
OUTPUT_BASE_DIR = (
    Path.home() / "OneDrive" / "Twitch" / "Abrechnungen" / "Whatnot_Rechnungen_und_Belege"
)

# Eigener, separater Chrome-Profilordner (NICHT der normale Chrome-Pfad).
# Chrome verweigert die DevTools-Fernsteuerung explizit für das echte
# Standardprofil (Sicherheitsmaßnahme gegen genau diese Art der Übernahme
# eines bereits eingeloggten Profils). Deshalb: einmalig manuell (mit
# normalem, nicht automatisiertem Chrome) in diesem eigenen Ordner bei
# Whatnot einloggen – siehe setup_login.py – danach kann Patchright die
# Sitzung hier automatisiert weiterverwenden.
import os

BROWSER_PROFILE_DIR = Path(os.environ["LOCALAPPDATA"]) / "ClaudeRechnungstool" / "browser_profile"

WHATNOT_BASE_URL = "https://www.whatnot.com"
WHATNOT_SHIPMENTS_URL = f"{WHATNOT_BASE_URL}/dashboard/shipments"
WHATNOT_ORDERS_URL = f"{WHATNOT_BASE_URL}/dashboard/orders"
WHATNOT_LOGIN_URL = f"{WHATNOT_BASE_URL}/login"
