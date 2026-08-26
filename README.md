# WoW Nemesis Launcher

Jednoduchý lokálny launcher pre World of Warcraft 2.4.3. Po kliknutí na uložený účet spustí `WoW.exe`, počká na jeho okno a cez klávesnicu odošle prihlasovacie údaje.

Rozhranie používa vlastné tmavé fantasy pozadie a zlato-antracitovú vizuálnu tému inšpirovanú webom Project Nemesis.

## Bezpečnosť

- Heslá sú šifrované pomocou Windows DPAPI a môže ich odomknúť iba rovnaký používateľ Windows na rovnakom počítači.
- Konfigurácia je uložená v `%APPDATA%\WoWNemesisLauncher\config.json`.
- Aplikácia nečíta ani nemení pamäť WoW procesu a neautomatizuje gameplay.
- Automatické písanie cez PyAutoGUI znamená, že heslo je počas prihlasovania krátko prítomné v pamäti aplikácie. Launcher používaj iba na dôveryhodnom počítači.

## Spustenie zo zdrojového kódu

Vyžaduje Windows a Python 3.10 alebo novší.

```bat
python -m pip install -r requirements.txt
python main.py
```

Pri prvom spustení vyber `WoW.exe`, pridaj účet a klikni na jeho veľké tlačidlo. Počas automatického prihlasovania nepoužívaj myš ani klávesnicu.

## Vytvorenie EXE

Spusti `build.bat`. Výsledok bude:

```text
dist\WoW_Nemesis_Launcher.exe
```

## Ladenie prihlasovania

V **Nastaveniach** možno upraviť:

- timeout čakania na vytvorenie okna WoW,
- oneskorenie medzi zobrazením okna a písaním údajov,
- automatické zatvorenie launcheru.

Ak launcher začne písať skôr než sa zobrazí prihlasovací formulár, zvýš oneskorenie po zobrazení okna.
