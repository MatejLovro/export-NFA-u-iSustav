"""
main.py

Ulazna tocka aplikacije. Pokrenite s:

    python main.py

ili kao kompajlirani .exe - param.ini se u oba slucaja trazi u istom
folderu gdje se nalazi skripta/izvrsna datoteka (ne u trenutnom radnom
direktoriju, koji moze biti drugaciji kad se .exe pokrene dvoklikom).
"""

import os
import sys

def get_app_dir() -> str:
    """Vraca folder gdje se nalazi .exe (kompajlirano) ili main.py (razvoj)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


if __name__ == "__main__":
    os.chdir(get_app_dir())  # param.ini, dbf_reader itd. sad rade relativno na ovaj folder
    from gui.main_window import launch_app
    launch_app()