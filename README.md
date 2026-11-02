# WoW Nemesis Launcher v1.12

Jednoduchý lokálny launcher pre World of Warcraft 2.4.3. Po kliknutí na uložený účet spustí `WoW.exe`, počká na jeho okno a cez klávesnicu odošle prihlasovacie údaje.

Rozhranie používa tmavé modré karty, tlmené fantasy pozadie, zlaté akcenty a samostatné ovládanie každého účtu. PID/HWND a úpravy sú dostupné po rozbalení detailov cez „⋯“ alebo „Nastaviť“. Nástroje sú v hornom menu. Zoznam sa pri zmene stavu nebuduje znova, detaily sa rozbaľujú plynulo a škálovanie pozadia používa odložené prekreslenie pri zmene veľkosti okna.

Od verzie 1.4 používa frontend knižnicu [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) 6.0.0 (MIT). Knižnica a jej licenčné súbory sú pribalené v priečinku `vendor`, aby bol build reprodukovateľný.

Autor: **Bc. Juraj Pekarík**

## Companion funkcie

- automatické nájdenie blízkej inštalácie `Wow.exe`,
- kontrola a bezpečná oprava `realmlist.wtf` pre GigaFun,
- samostatné spustenie oficiálneho `GigaFun_Launcher.exe` na aktualizáciu alebo opravu hry,
- samostatné spustenie externého WowOpenBox nástroja na rozloženie okien,
- integrovaný autocast pod každým účtom: dynamický počet klávesov s vlastnými intervalmi, predvolene `3` každých `500 ms`, spoločné Štart/Stop pre účet,
- mapovanie externého autoclicker EXE nástroja a jeho ručné spustenie z launcheru,
- voliteľná zmena pozadia launcheru cez Nastavenia,
- uloženie posledného spusteného WoW `HWND`/PID pre externé nástroje,
- samostatné držanie `PID/HWND` pri každom spustenom účte pri multiboxe,
- zobrazenie posledného WoW `PID/HWND` priamo pri naposledy spustenom účte,
- automatické vyčistenie `PID/HWND` pri zavretí posledného WoW okna,
- stabilnejšie sledovanie posledného WoW PID a automatické obnovenie HWND pri zmene okna,
- lepšie škálovanie pozadia vo fullscreen režime a výraznejšie písmo,
- detekcia bežiaceho WOB procesu a možnosť ukončiť ho pri konflikte hotkeyov,
- následné spustenie WoW a prihlásenie vybraného účtu bez zatvorenia launcheru,
- nastaviteľný relatívny klik do login poľa, vhodný aj pre rôzne rozloženia okien vo WowOpenBoxe,
- rolovateľný zoznam vhodný aj pre veľa účtov,
- ručné zoradenie účtov cez malé rozbaľovacie menu pri účte,
- možnosť dočasne zobraziť uložené heslo v okne úpravy účtu,
- voliteľné bezpečné uloženie registrovaného e-mailu účtu cez Windows DPAPI.

Oficiálny GigaFun launcher nie je súčasťou projektu ani výsledného EXE.

## WowOpenBox

WowOpenBox je externý nástroj. Nie je pribalený do EXE launcheru; používateľ si nastaví cestu k svojmu priečinku `WOB2025` v Nastaveniach.

Ak je v priečinku oficiálne `WOB2025`/`WowOpenBox`/`OpenMultiBoxing` EXE, launcher ho nájde aj v podpriečinku a spustí ho.

Autoclicker je voliteľný externý `.exe` nástroj. Autocast je súčasťou launcheru aj výsledného EXE a neposiela príkazy externému programu. Pod účtom klikni na Nastaviť. Cez + Pridať autocast pridaj ľubovoľný počet riadkov; každý obsahuje vlastnú klávesu a interval (100 až 3600000 ms). Riadok odstrániš cez ×. Štart spustí všetky autocasty účtu naraz s nezávislým časovaním; Stop všetky zastaví. Predchádzajúce nastavenie jednej klávesy sa automaticky načíta ako prvý riadok. Stop ostáva stále dostupný v karte účtu. Podporované sú A–Z, 0–9, F1–F12, SPACE, TAB, ENTER a UP/DOWN/LEFT/RIGHT. Nastavenia sa ukladajú pre každý účet; beh sa po reštarte automaticky neobnovuje.

Autocast posiela WM_KEYDOWN/WM_KEYUP priamo do WoW okna účtu bez aktivácie okna. Automaticky používa PID/HWND získané pri spustení účtu a pri hre spustenej launcherom sleduje pôvodný objekt procesu bez opätovného OpenProcess. Ak pri už bežiacej hre Windows odmietne prístup k procesu, sleduje presnú identitu okna (PID, vlákno a triedu) a neprepína sa na iné okno. Zastaví sa pri zavretí okna/procesu, zmazaní účtu, opätovnom spustení účtu alebo zavretí launcheru. Počas automatického prihlasovania sú všetky autocasty pozastavené. Niektorí herní klienti môžu správy na pozadí ignorovať; funkčnosť v konkrétnom WoW klientovi treba overiť v hre. Pri používaní autocastu nechaj launcher otvorený.

Pri spustení externého nástroja launcher pošle posledné WoW okno aj cez environment premenné: `WOW_NEMESIS_LAST_HWND`, `WOW_NEMESIS_LAST_PID`, `WOW_NEMESIS_LAST_ACCOUNT`, `WOW_NEMESIS_LAST_USERNAME` a `WOW_NEMESIS_CONFIG`.

## Bezpečnosť

- Heslá sú šifrované pomocou Windows DPAPI a môže ich odomknúť iba rovnaký používateľ Windows na rovnakom počítači.
- Konfigurácia je uložená v `%APPDATA%\WoWNemesisLauncher\config.json`.
- Aplikácia nečíta ani nemení pamäť WoW procesu. Voliteľný autocast opakuje nastavenú klávesu v príslušnom okne hry.
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
dist\WoW_Nemesis_Launcher_v1.12\WoW_Nemesis_Launcher_v1.12.exe
```

Verzie používajú formát `major.minor.patch`. Oprava bude napríklad `v1.1.1`, nová funkcia `v1.2.0`.

### Podpis EXE

Pre menšie množstvo false-positive hlásení odporúčame buildovať release ako priečinok cez `build_release_zip.bat` a podpísať EXE cez `sign_release.bat` platným Authenticode code-signing certifikátom. Certifikát nie je súčasťou projektu.

```bat
set SIGN_CERT_PFX=C:\certifikaty\code-signing.pfx
set SIGN_CERT_PASSWORD=tajne-heslo
sign_release.bat dist\WoW_Nemesis_Launcher_v1.8.1.exe
```

Skript predvolene podpisuje `dist\WoW_Nemesis_Launcher_v1.8.1.exe`, takže parameter môžeš vynechať, ak chceš podpísať práve túto verziu. Distribuuj iba podpísaný ZIP, napríklad `dist\WoW_Nemesis_Launcher_v1.8.1_signed.zip`, nie celý pracovný priečinok projektu.

## Ladenie prihlasovania

V **Nastaveniach** možno upraviť:

- timeout čakania na vytvorenie okna WoW,
- oneskorenie medzi zobrazením okna a písaním údajov,
- pozícia kliknutia do login poľa v percentách šírky/výšky WoW okna,
- automatické zatvorenie launcheru.

Ak launcher začne písať skôr než sa zobrazí prihlasovací formulár, zvýš oneskorenie po zobrazení okna.

Build vylučuje nepoužívané moduly pre snímky obrazovky, pomocné okná, numerické výpočty a sieťové protokoly. Launcher sám nevolá HTTP ani neotvára sieťové spojenia. Ručne spustená hra alebo externý updater môže komunikovať samostatne. Sieťové záznamy sandboxu treba vyhodnotiť podľa procesu, ktorý spojenie vytvoril.
