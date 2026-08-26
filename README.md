# WoW Nemesis Launcher v1.7.1

Jednoduchý lokálny launcher pre World of Warcraft 2.4.3. Po kliknutí na uložený účet spustí `WoW.exe`, počká na jeho okno a cez klávesnicu odošle prihlasovacie údaje.

Rozhranie používa vlastné tmavé fantasy pozadie a zeleno-zlatú vizuálnu tému inšpirovanú vzhľadom GigaFun launcheru.

Od verzie 1.4 používa frontend knižnicu [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) 6.0.0 (MIT). Knižnica a jej licenčné súbory sú pribalené v priečinku `vendor`, aby bol build reprodukovateľný.

Autor: **Bc. Juraj Pekarík**

## Companion funkcie

- automatické nájdenie blízkej inštalácie `Wow.exe`,
- kontrola a bezpečná oprava `realmlist.wtf` pre GigaFun,
- samostatné spustenie oficiálneho `GigaFun_Launcher.exe` na aktualizáciu alebo opravu hry,
- samostatné spustenie externého WowOpenBox nástroja na rozloženie okien,
- mapovanie externého autoclicker/autocast EXE nástroja a jeho ručné spustenie z launcheru,
- uloženie posledného spusteného WoW `HWND`/PID pre externé nástroje,
- detekcia bežiaceho WOB procesu a možnosť ukončiť ho pri konflikte hotkeyov,
- následné spustenie WoW a prihlásenie vybraného účtu bez zatvorenia launcheru,
- nastaviteľný relatívny klik do login poľa, vhodný aj pre rôzne rozloženia okien vo WowOpenBoxe,
- rolovateľný zoznam vhodný aj pre veľa účtov,
- voliteľné bezpečné uloženie registrovaného e-mailu účtu cez Windows DPAPI.

Oficiálny GigaFun launcher nie je súčasťou projektu ani výsledného EXE.

## WowOpenBox

WowOpenBox je externý nástroj. Nie je pribalený do EXE launcheru; používateľ si nastaví cestu k svojmu priečinku `WOB2025` v Nastaveniach.

Ak je v priečinku oficiálne `WOB2025`/`WowOpenBox`/`OpenMultiBoxing` EXE, launcher ho nájde aj v podpriečinku a spustí ho.

Autoclicker a autocast sú iba voliteľne mapované externé `.exe` nástroje. Nie sú súčasťou launcheru; aplikácia si len uloží cestu a spustí ich na kliknutie.

Pri spustení externého nástroja launcher pošle posledné WoW okno aj cez environment premenné: `WOW_NEMESIS_LAST_HWND`, `WOW_NEMESIS_LAST_PID`, `WOW_NEMESIS_LAST_ACCOUNT`, `WOW_NEMESIS_LAST_USERNAME` a `WOW_NEMESIS_CONFIG`.

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
dist\WoW_Nemesis_Launcher_v1.7.1.exe
```

Verzie používajú formát `major.minor.patch`. Oprava bude napríklad `v1.1.1`, nová funkcia `v1.2.0`.

## Ladenie prihlasovania

V **Nastaveniach** možno upraviť:

- timeout čakania na vytvorenie okna WoW,
- oneskorenie medzi zobrazením okna a písaním údajov,
- pozícia kliknutia do login poľa v percentách šírky/výšky WoW okna,
- automatické zatvorenie launcheru.

Ak launcher začne písať skôr než sa zobrazí prihlasovací formulár, zvýš oneskorenie po zobrazení okna.
