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
4. Commit et tag : `git tag v1.1`
5. Push : `git push && git push --tags`
6. GitHub Actions build et publie automatiquement l'installer en GitHub Release

**Important** : les 3 valeurs (main.py, version.txt, setup.iss) doivent toujours être synchronisées.

**SHA-256** : lors de la création de la release GitHub, inclure le hash SHA-256 de `InstallEditeurPDF.exe` dans le body de la release au format : `SHA256: <hash>`. L'app vérifie ce hash avant d'exécuter l'installeur téléchargé.

## CI/CD

- GitHub Actions workflow dans `.github/workflows/build.yml`
- Déclenché sur push d'un tag `v*`
- Build PyInstaller + Inno Setup sur `windows-latest`
- Publie `InstallEditeurPDF.exe` en GitHub Release

## Système de mise à jour automatique

- Au lancement, l'app fetch `version.txt` sur GitHub (raw.githubusercontent.com)
- Compare avec `VERSION` dans main.py (version compilée dans l'exe)
- Si différent → toast cliquable proposant la mise à jour
- Au clic, l'installer est téléchargé depuis GitHub Releases puis lancé automatiquement

## Configuration

- `config.ini` : fichier local (gitignored), utilisé pour le build PyInstaller
- `config.ini.example` : template versionné sans infos sensibles
