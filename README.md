# Editeur PDF

Editeur PDF de bureau construit avec PySide6 et PyMuPDF. Permet de visualiser, reorganiser, annoter et exporter des documents PDF.

## Fonctionnalites

- Glisser-deposer de fichiers PDF
- Reorganisation des pages par drag & drop
- Ajout de zones de texte editables (police, taille, couleur, bordure, fond)
- Apercu et lecture plein ecran avec zoom
- Navigation main (clic gauche maintenu pour deplacer la vue)
- Export PDF (tout, selection, plage de pages)
- Raccourcis clavier (navigation, copier/coller, supprimer)

## Installation pour les utilisateurs

Un seul fichier suffit : **`InstallEditeurPDF.exe`**

1. Recuperer `InstallEditeurPDF.exe` depuis la derniere [GitHub Release](https://github.com/yannsokol-web/EDITEUR2PDF/releases/latest)
2. Double-cliquer dessus
3. L'installation se fait automatiquement (aucun prerequis, pas besoin de Python)
4. Un raccourci **Editeur PDF** apparait sur le Bureau
5. Pour desinstaller : Parametres Windows > Applications > Editeur PDF > Desinstaller

## Developpement

### Prerequis

- Python 3.10 ou superieur
- Windows 10/11

### Lancer depuis les sources

```bash
git clone https://github.com/yannsokol-web/EDITEUR2PDF.git
cd EDITEUR2PDF
pip install PySide6 PyMuPDF
python main.py
```

### Generer l'installeur

L'installeur est cree en deux etapes : compilation de l'app avec PyInstaller, puis empaquetage avec Inno Setup.

1. **Installer les outils** (une seule fois) :
   - Python 3.10+ avec `pip install PySide6 PyMuPDF pyinstaller`
   - [Inno Setup 6](https://jrsoftware.org/isdl.php) (installation par defaut)

2. **Lancer le build** :

```bash
build.bat
```

Cela produit `installer_output\InstallEditeurPDF.exe`, pret a etre distribue.

### Structure du build

| Fichier | Role |
|---------|------|
| `main.py` | Code source de l'application |
| `EditeurPDF.spec` | Configuration PyInstaller |
| `setup.iss` | Script Inno Setup (installeur) |
| `build.bat` | Automatise compilation + creation installeur |
| `logoediteurpdf.ico` | Icone de l'application |
