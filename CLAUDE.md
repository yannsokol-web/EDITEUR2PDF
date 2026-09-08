# Editeur PDF - Notes projet

## Stack
- Python 3.10+ / PySide6 (Qt6) / PyMuPDF (fitz)
- Build : PyInstaller → Inno Setup
- Repo : github.com/yannsokol-web/EDITEUR2PDF

## Publier une mise à jour

Quand le code source est modifié et prêt à être déployé :

1. Incrémenter `VERSION` dans `main.py` (ex: `"1.5"` → `"1.6"`)
2. Mettre à jour `AppVersion` **et** `AppVerName` dans `setup.iss` avec la même valeur
3. Commit et tag : `git tag v1.6`
4. Push : `git push && git push --tags`
5. GitHub Actions build et publie automatiquement l'installer en GitHub Release

**Important** : les 2 valeurs (`main.py`, `setup.iss`) doivent toujours être synchronisées.
Le tag doit valoir `v` + cette même valeur, c'est lui que l'app compare à sa propre version.

**SHA-256** : la CI calcule le hash de `InstallEditeurPDF.exe` et l'écrit dans le body de
la release au format `SHA256: <hash>` (étape « Compute installer SHA-256 » dans
`build.yml`). L'app vérifie ce hash avant d'exécuter l'installeur téléchargé et refuse la
mise à jour s'il est absent — ne pas supprimer cette ligne en éditant les notes de version.

## CI/CD

- GitHub Actions workflow dans `.github/workflows/build.yml`
- Déclenché sur push d'un tag `v*`
- Build PyInstaller + Inno Setup sur `windows-latest`
- Publie `InstallEditeurPDF.exe` en GitHub Release, avec le SHA-256 dans le body

## Système de mise à jour automatique

- Au lancement, l'app interroge l'API GitHub Releases (`/releases/latest`) et lit `tag_name`
- Compare avec `VERSION` dans main.py (version compilée dans l'exe), par tuple d'entiers :
  la mise à jour n'est proposée que si la release est **strictement plus récente**
- Si oui → toast cliquable proposant la mise à jour
- Au clic, l'installeur est téléchargé depuis GitHub Releases, son SHA-256 est vérifié
  contre celui du body de la release, puis il est lancé après confirmation

## Tests

Aucun test automatisé dans le dépôt : la validation se fait à la main via `python main.py`.
Pour un test hors écran, `QT_QPA_PLATFORM=offscreen` fonctionne et permet de piloter
`MainWindow` depuis un script.
