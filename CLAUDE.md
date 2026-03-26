# Editeur PDF - Notes projet

## Stack
- Python 3.10+ / PySide6 (Qt6) / PyMuPDF (fitz)
- Build : PyInstaller → Inno Setup
- Repo : github.com/yannsokol-web/EDITEUR2PDF

## Publier une mise à jour

Quand le code source est modifié et prêt à être déployé :

1. Incrémenter `VERSION` dans `main.py` (ex: `"1.0"` → `"1.1"`)
2. Mettre à jour `version.txt` à la racine avec la même valeur (ex: `1.1`)
3. Mettre à jour `AppVersion` dans `setup.iss` avec la même valeur
4. Push sur GitHub
5. Rebuild avec `build.bat`
6. Copier `installer_output\InstallEditeurPDF.exe` sur `\\\Media\03 - Logiciels & Divers\07 - Logiciel Yann\`

**Important** : les 3 valeurs (main.py, version.txt, setup.iss) doivent toujours être synchronisées.

## Système de mise à jour automatique

- Au lancement, l'app fetch `version.txt` sur GitHub (raw.githubusercontent.com)
- Compare avec `VERSION` dans main.py (version compilée dans l'exe)
- Si différent → toast cliquable proposant la mise à jour
- Lance l'installateur depuis le chemin UNC : `\\\Media\03 - Logiciels & Divers\07 - Logiciel Yann\InstallEditeurPDF.exe`
