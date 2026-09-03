# Whatnot Rechnungstool

Automatisiert die Erstellung von MwSt-Rechnungen im Whatnot-Verkäufer-Hub
(Sendungsliste) und lädt die erzeugten PDFs herunter, sortiert nach
Jahr/Monat.

## Installation (einmalig, pro Rechner)

1. Diesen Ordner auf den Ziel-Rechner kopieren (z. B. per Git-Klon oder als ZIP).
2. `install.bat` doppelklicken.
   - Installiert bei Bedarf automatisch Python 3.12 und Google Chrome
     (über winget, oder als Direkt-Download falls winget fehlt).
   - Legt eine virtuelle Umgebung an (`.venv`) und installiert die
     Python-Abhängigkeiten (Patchright).
3. `login_setup.bat` doppelklicken und im sich öffnenden Chrome-Fenster
   einmalig manuell bei Whatnot einloggen (auch "Mit Google anmelden",
   falls genutzt). Fenster danach schließen. Die Sitzung bleibt in einem
   eigenen, separaten Chrome-Profil gespeichert.

## Benutzung

`start.bat` doppelklicken. Show auswählen (oder "Alle Sendungen"), MwSt-Satz
eintragen, ggf. Testlauf aktivieren, Start klicken.

## Hinweise

- Rechnungs-PDFs landen unter `%USERPROFILE%\OneDrive\Twitch\Abrechnungen\Whatnot_Rechnungen_und_Belege\<Jahr>\<Monat>`
  (siehe [config.py](config.py), `OUTPUT_BASE_DIR`).
- Der Login läuft in einem eigenen Chrome-Profil unter
  `%LOCALAPPDATA%\ClaudeRechnungstool\browser_profile` – nicht dem normalen
  Chrome-Profil, da Whatnot/Chrome die automatisierte Fernsteuerung des
  echten Standardprofils verweigert.
- Bei 0% MwSt wird automatisch ein Kleinunternehmer-Hinweis (§19 UStG) in
  die Rechnungsnotizen eingefügt.

## Manuelle Installation (falls `install.bat` nicht genutzt werden soll)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python setup_login.py   # einmalig, manueller Login
.venv\Scripts\python app.py
```

## Beitragen

Pull Requests sind willkommen. Bitte beschreibe kurz, welches Problem dein
Änderungsvorschlag löst.

## Lizenz

Noch nicht festgelegt.
