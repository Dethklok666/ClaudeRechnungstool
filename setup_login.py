"""Einmaliges, manuelles Login-Setup.

Startet ein ganz normales (nicht automatisiertes) Chrome-Fenster mit einem
eigenen, separaten Profilordner. Darin bitte einmalig manuell bei Whatnot
einloggen (inkl. "Mit Google anmelden", falls genutzt) und das Fenster dann
schließen. Die Sitzung bleibt im Profilordner gespeichert und wird danach von
app.py automatisiert weiterverwendet.
"""

import subprocess

import config

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main() -> None:
    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Öffne Chrome mit Profilordner: {config.BROWSER_PROFILE_DIR}")
    print("Bitte dort bei Whatnot einloggen, danach das Fenster schließen.")
    subprocess.run(
        [
            CHROME_EXE,
            f"--user-data-dir={config.BROWSER_PROFILE_DIR}",
            config.WHATNOT_LOGIN_URL,
        ]
    )


if __name__ == "__main__":
    main()
