# Éditeur PDF

Éditeur PDF de bureau basé sur PySide6 et PyMuPDF.

## Cloner le dépôt

```bash
git clone https://github.com/yannsokol-web/EDITEUR2PDF.git
cd EDITEUR2PDF
```

## Prérequis

- Python 3.10+

## Installation

```bash
pip install PySide6 PyMuPDF
```

## Lancement

```bash
python main.py
```

## Compilation en exécutable (.exe)

Double-cliquez sur **`build.bat`** — il installe les dépendances et compile automatiquement.

## Installation sur un PC

1. Après compilation, double-cliquez sur **`install.bat`**
2. L'application est copiée dans `%LOCALAPPDATA%\EditeurPDF`
3. Un raccourci **EditeurPDF** apparaît sur le bureau

Pour déployer sur d'autres machines : copiez le dossier `dist\EditeurPDF\` + `install.bat` sur le PC cible, puis lancez `install.bat`.
