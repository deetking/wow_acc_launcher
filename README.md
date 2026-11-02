# WoW Nemesis Launcher 1.12

Launcher pre **WoW 2.4.3 na Windows 64-bit**. Uložené účty, automatické prihlásenie, autocasty a Anti-AFK v jednej aplikácii.

## Stiahnuť a spustiť

1. Otvor [Releases](https://github.com/deetking/wow_acc_launcher/releases) a vyber vydanie **1.12**.
2. V časti **Assets** stiahni **WoW_Nemesis_Launcher_v1.12_release.zip**.
3. Rozbaľ **celý ZIP** do vlastného priečinka a spusti **WoW_Nemesis_Launcher_v1.12.exe**.
4. V **SETTINGS** nastav cestu k svojmu `WoW.exe`, pridaj účet a spusti hru.

**Python ani inštalácia nie sú potrebné.** Priečinok `_internal` musí zostať vedľa EXE. WoW klient nie je súčasťou balíka. Položky GitHubu „Source code“ a „Code → Download ZIP“ obsahujú zdrojový kód pre vývojárov, nie hotovú aplikáciu.

## Ovládanie

- **Autocast:** pod účtom otvor **Nastaviť**, pridaj klávesy a intervaly; **Štart/Stop** ovláda autocasty daného účtu. Predvolené nastavenie je `3` každých `500 ms`, minimum `100 ms`.
- **Spoločná skratka:** v **SETTINGS** si nastav napríklad `F9` alebo `Ctrl+Alt+F8`. Zapne autocasty účtom so stavom **Spustený**; ak už nejaké bežia, ďalšie stlačenie ich všetky vypne. Funguje aj keď je hra v popredí. Počas otvorených Nastavení je skratka pozastavená.
- **Anti-AFK:** checkbox pri účte zapne krátke stlačenie `W` na `60 ms` každých `5 minút`. Je nezávislé od autocastu. Voľba sa ukladá a aktivuje po prihlásení účtu cez launcher.
- **Toolbar:** účty, oficiálny updater, WowOpenBox, autoclicker a nastavenia. Externé nástroje sú voliteľné a nepribaľujú sa; nastav cestu k vlastnej kópii.
- **Pozadie:** v Nastaveniach môžeš zvoliť vlastný obrázok alebo obnoviť pôvodné pozadie.

Pri autocaste a Anti-AFK nechaj launcher otvorený. Počas automatického prihlasovania nepoužívaj myš ani klávesnicu. Správanie klávesov na pozadí závisí od herného klienta a jeho nastavenia.

## Nastavenia a aktualizácia

Účty sa ukladajú lokálne do `%APPDATA%\WoWNemesisLauncher\config.json`. Heslá a voliteľný e-mail chráni Windows DPAPI pod daným Windows účtom; prihlasovacie údaje nie sú súčasťou release ZIP-u. Konfiguračný súbor nezverejňuj.

Pri aktualizácii zavri launcher a nové vydanie rozbaľ do nového priečinka. Nastavenia a účty sa načítajú automaticky z rovnakého umiestnenia v APPDATA.

## Pre vývojárov

Windows 64-bit a Python **3.12 64-bit**. Rozhranie CustomTkinter a jeho závislosti sú vo `vendor/` vrátane licenčných súborov.

```bat
python -m pip install -r requirements.txt
python main.py
```

Testy:

```bat
python -m unittest test_autocast test_release
```

### Vytvorenie balíka

Spusti `build.bat` alebo kompatibilný `build_release_zip.bat`. Výsledok:

```text
dist/WoW_Nemesis_Launcher_v1.12/WoW_Nemesis_Launcher_v1.12.exe
dist/WoW_Nemesis_Launcher_v1.12_release.zip
dist/WoW_Nemesis_Launcher_v1.12_release.zip.sha256
```

Build kontroluje zhodu `APP_VERSION` v `main.py` s Windows metadátami vo `version_info.txt`. ZIP obsahuje jeden priečinok aplikácie s EXE, README a celým `_internal`. Balí sa iba distribučný priečinok; osobná konfigurácia, certifikáty a vývojové súbory sa nepribaľujú.

Kontrola spustenia s izolovanou testovacou konfiguráciou:

```bat
python tools/smoke_test.py
```

Autor: **Bc. Juraj Pekarík**
