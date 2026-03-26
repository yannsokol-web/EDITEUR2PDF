# Editeur PDF

Editeur PDF de bureau construit avec PySide6 et PyMuPDF. Permet de visualiser, reorganiser, annoter et exporter des documents PDF.

## Fonctionnalites

- Glisser-deposer de fichiers PDF
- Reorganisation des pages par drag & drop
- Ajout de zones de texte editables (police, taille, couleur, bordure, fond)
- Apercu et lecture plein ecran avec zoom
- Export PDF (tout, selection, plage de pages)
- Raccourcis clavier (navigation, copier/coller, supprimer)

## Prerequis

- Python 3.10 ou superieur
- Windows 10/11

## Installation

1. **Cloner le depot**

```bash
git clone https://github.com/yannsokol-web/EDITEUR2PDF.git
cd EDITEUR2PDF
```

2. **Installer les dependances**

```bash
pip install PySide6 PyMuPDF
```

3. **Lancer l'application**

```bash
python main.py
```

## Creer un executable (optionnel)

Pour generer un `.exe` autonome :

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name EditeurPDF --icon logoediteurpdf.ico --add-data "logoediteurpdf.ico;." main.py
```

L'executable se trouvera dans le dossier `dist/EditeurPDF/`.
