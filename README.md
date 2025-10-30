# 🔍 Check Promotions

Un script Python pour **détecter automatiquement la présence de promotions** sur la page d’accueil d’une liste de sites web.

Il analyse le contenu HTML de chaque URL, détecte la présence de mots-clés liés aux promotions dans plusieurs langues (français, anglais), ainsi que des mentions de remises en pourcentage (ex : `-50%`, `jusqu’à 60 %`, `70% off`).

---

## 🚀 Fonctionnalités

- ✅ Lecture d’une liste d’URL depuis un fichier texte (`websites.txt`)
- ✅ Téléchargement robuste avec **retries**, timeout et **User-Agent réaliste**
- ✅ Vérification du **code HTTP** (ignore les pages non disponibles)
- ✅ Détection **multi-langues** des mots-clés de promotion
- ✅ Détection de remises (`50%`, `60%`, `70%`, etc.)
- ✅ Suivi automatique des redirections (`final_url`)
- ✅ Export optionnel en **CSV**
- ✅ Gestion fine des erreurs (`timeout`, `SSL`, etc.)

---

## 🧰 Installation

### 1. Cloner ou copier le script
```bash
git clone https://github.com/eloiseschmitt/alert-promo.git
cd alert-promo
```

### Commandes principales
python scan_websites.py --input websites.txt

python scan_websites.py --input websites.txt --output results.csv

---

## 🗂️ Format de `websites.txt`

- Les lignes vides ou commentées (`# ...`) sont ignorées.
- Pour regrouper des URLs, ajoute une ligne `NOM_DE_CATEGORIE:` puis les URLs associées.
- Exemple :

  ```text
  FEMMES:
  https://www.armedangels.com/fr-fr
  https://thinkingmu.com/fr

  HOMMES:
  https://jaspebydiane.fr/
  https://minuitsurterre.com/
  ```

- Les tableaux de l’interface et du rapport e-mail afficheront une ligne d’en-tête par catégorie et marqueront les différences avec le scan précédent.

---

## ✅ Tests

- `python3 -m pip install -r requirements.txt`
- `python3 -m pytest tests/test_app_approval.py`
