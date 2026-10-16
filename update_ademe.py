#!/usr/bin/env python3
"""
Met à jour data/ademe.js à partir d'un export CSV de la Base Carbone® ADEME.

USAGE
    python scripts/update_ademe.py chemin/vers/base-carbone.csv --version "V23.7"
    python scripts/update_ademe.py base-carbone.csv --version "V23.7" --dry-run     (rapport seul, rien n'est écrit)

CE QUE FAIT LE SCRIPT
  1. lit le CSV ADEME (séparateur ; ou , détecté automatiquement, UTF-8 ou Latin-1) ;
  2. filtre les lignes valides, calcule libellé / catégorie / rubrique / unité de saisie ;
  3. compare avec la base actuelle (data/ademe.js) et écrit scripts/rapport_mise_a_jour.md :
       facteurs ajoutés, supprimés, dont la valeur a changé (alerte au-delà du seuil), lignes rejetées ;
  4. vérifie que chaque boisson en kg a une masse volumique (data/densites_boissons.js) ;
  5. réécrit data/ademe.js (sauvegarde de l'ancien fichier dans data/archives/).

Ne dépend que de la bibliothèque standard Python 3.8+.
"""
import argparse, csv, io, json, re, shutil, sys, datetime
from collections import Counter, defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ADEME_JS = RACINE / "data" / "ademe.js"
DENS_JS = RACINE / "data" / "densites_boissons.js"
CONFIG = Path(__file__).resolve().parent / "rubriques.json"
RAPPORT = Path(__file__).resolve().parent / "rapport_mise_a_jour.md"


# ---------- lecture ----------
def lire_csv(chemin):
    brut = Path(chemin).read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texte = brut.decode(enc); break
        except UnicodeDecodeError:
            continue
    echant = texte[:5000]
    sep = ";" if echant.count(";") >= echant.count(",") else ","
    return list(csv.DictReader(io.StringIO(texte), delimiter=sep))


def nombre(x):
    if x is None: return None
    x = str(x).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try: return float(x)
    except ValueError: return None


def charger_js(chemin, nom):
    """Extrait le JSON d'une déclaration 'const NOM = <json>;'."""
    s = Path(chemin).read_text(encoding="utf-8")
    i = s.index("const " + nom + " =") + len("const " + nom + " =")
    debut = min(p for p in (s.find("[", i), s.find("{", i)) if p != -1)
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(s[debut:])
    return obj


# ---------- conversion ----------
def convertir(lignes, cfg):
    cols = cfg["colonnes_csv"]
    manquantes = [v for k, v in cols.items() if lignes and v not in lignes[0]]
    if manquantes:
        sys.exit("ERREUR : colonnes introuvables dans le CSV : %s\n"
                 "Colonnes présentes : %s\nAdaptez 'colonnes_csv' dans scripts/rubriques.json."
                 % (manquantes, list(lignes[0].keys())))
    unites = cfg["unites_ademe_vers_saisie"]
    retirer = cfg["categorie_niveaux_a_retirer"]
    sortie, rejets = [], Counter()
    exemples_rejets = defaultdict(list)

    def rejeter(raison, ligne):
        rejets[raison] += 1
        if len(exemples_rejets[raison]) < 5:
            exemples_rejets[raison].append(ligne.get(cols["nom_base"], "?"))

    for lg in lignes:
        if lg[cols["type_ligne"]].strip() not in cfg["type_ligne_accepte"]:
            rejeter("type de ligne non retenu", lg); continue
        if lg[cols["statut"]].strip() not in cfg["statuts_acceptes"]:
            rejeter("statut non retenu (archivé, valide spécifique…)", lg); continue
        v = nombre(lg[cols["valeur"]])
        if v is None:
            rejeter("valeur manquante ou illisible", lg); continue
        u_brut = lg[cols["unite"]].strip()
        u_brut = u_brut.split("/", 1)[1].strip() if "/" in u_brut else u_brut
        iu = unites.get(u_brut)
        if iu is None:
            rejeter("unité inconnue : « %s » (ajouter à unites_ademe_vers_saisie)" % u_brut, lg); continue
        base = lg[cols["nom_base"]].strip()
        attr = lg[cols["nom_attribut"]].strip()
        label = base + (" - " + attr if attr else "")
        niveaux = [n.strip() for n in lg[cols["categorie"]].split(" > ") if n.strip()]  # séparateur « espace > espace » (certains niveaux commencent par « > »)
        cat = " > ".join(niveaux[retirer:] if len(niveaux) > retirer else niveaux)
        if not cat:
            rejeter("catégorie vide", lg); continue
        classement = classer(cat, iu, cfg)
        if classement is None:
            rejeter("rubrique impossible à déterminer", lg); continue
        ri, r, il = classement
        sortie.append({"l": label, "c": cat, "r": r, "ri": ri, "iu": iu, "il": il, "v": v,
                       "t": lg[cols["tags"]].strip()})
    return sortie, rejets, exemples_rejets


def classer(cat, iu, cfg):
    niv = cat.split(" > ")
    for n in (3, 2, 1):
        cle = " > ".join(niv[:n]) + " || " + iu
        reg = cfg["regles"].get(str(n), {}).get(cle)
        if reg: return reg
    return cfg["repli_par_unite"].get(iu)


# ---------- comparaison ----------
def comparer(anciens, nouveaux, seuil):
    ka = {(x["l"], x["c"]): x for x in anciens}
    kn = {(x["l"], x["c"]): x for x in nouveaux}
    ajoutes = [kn[k] for k in kn if k not in ka]
    supprimes = [ka[k] for k in ka if k not in kn]
    modifies = []
    for k in ka.keys() & kn.keys():
        a, n = ka[k], kn[k]
        if a["v"] != n["v"] or a["iu"] != n["iu"] or a["ri"] != n["ri"]:
            pct = (n["v"] - a["v"]) / a["v"] * 100 if a["v"] else float("inf")
            modifies.append((a, n, pct))
    modifies.sort(key=lambda t: -abs(t[2]) if t[2] != float("inf") else -1e18)
    return ajoutes, supprimes, modifies


def verifier_densites(nouveaux):
    dens = charger_js(DENS_JS, "DENSITES_BOISSONS")
    try: restent_kg = set(charger_js(DENS_JS, "BOISSONS_RESTANT_EN_KG"))
    except Exception: restent_kg = set()
    boissons_kg = [x for x in nouveaux if x["iu"] == "kg" and " > Boissons" in (" > " + x["c"])]
    sans = [x for x in boissons_kg if x["l"] not in dens and x["l"] not in restent_kg]
    obsoletes = [l for l in dens if not any(x["l"] == l for x in nouveaux)]
    return sans, obsoletes


# ---------- rapport ----------
def ecrire_rapport(args, anciens, nouveaux, ajoutes, supprimes, modifies, rejets, ex_rej, sans_dens, dens_obs, seuil):
    L = []
    L.append("# Rapport de mise à jour de la Base Carbone ADEME\n")
    L.append("Généré le %s — version : **%s** — fichier : `%s`\n" % (datetime.date.today().isoformat(), args.version, Path(args.csv).name))
    L.append("| | Nombre |\n|---|---|\n| Facteurs avant | %d |\n| Facteurs après | %d |\n| Ajoutés | %d |\n| Supprimés | %d |\n| Modifiés | %d |\n| Lignes du CSV rejetées | %d |\n"
             % (len(anciens), len(nouveaux), len(ajoutes), len(supprimes), len(modifies), sum(rejets.values())))
    grosses = [m for m in modifies if abs(m[2]) >= seuil]
    L.append("\n## 1. À vérifier en priorité\n")
    L.append("### Boissons sans masse volumique (%d)\nÀ ajouter dans `data/densites_boissons.js` (ou dans `BOISSONS_RESTANT_EN_KG`), sinon elles s'afficheront en kg.\n" % len(sans_dens))
    L += ["- %s" % x["l"] for x in sans_dens] or ["_Aucune._"]
    L.append("\n### Masses volumiques devenues orphelines (%d)\nBoissons de `densites_boissons.js` qui n'existent plus sous ce nom dans la base (renommées ou supprimées ?).\n" % len(dens_obs))
    L += ["- %s" % l for l in dens_obs] or ["_Aucune._"]
    L.append("\n### Variations ≥ %d %% (%d)\n" % (seuil, len(grosses)))
    L.append("| Facteur | Avant | Après | Variation |\n|---|---|---|---|")
    for a, n, pct in grosses[:200]:
        L.append("| %s | %s %s | %s %s | %s |" % (a["l"], a["v"], a["iu"], n["v"], n["iu"], "n/a" if pct == float("inf") else "%+.1f %%" % pct))
    if len(grosses) > 200: L.append("\n_… %d autres, voir la comparaison complète ci-dessous._" % (len(grosses) - 200))
    L.append("\n## 2. Lignes rejetées par le script\n")
    for raison, nb in rejets.most_common():
        L.append("- **%d** × %s — ex. : %s" % (nb, raison, "; ".join(ex_rej[raison])))
    if not rejets: L.append("_Aucune._")
    L.append("\n## 3. Supprimés (%d)\n" % len(supprimes))
    L += ["- %s _(%s)_" % (x["l"], x["c"]) for x in supprimes[:300]] or ["_Aucun._"]
    L.append("\n## 4. Ajoutés (%d)\n" % len(ajoutes))
    L += ["- %s _(%s)_ : %s %s" % (x["l"], x["c"], x["v"], x["iu"]) for x in ajoutes[:300]] or ["_Aucun._"]
    L.append("\n## 5. Autres modifications (%d)\n" % (len(modifies) - len(grosses)))
    L.append("| Facteur | Avant | Après | Variation |\n|---|---|---|---|")
    for a, n, pct in [m for m in modifies if abs(m[2]) < seuil][:300]:
        L.append("| %s | %s %s | %s %s | %s |" % (a["l"], a["v"], a["iu"], n["v"], n["iu"], "%+.1f %%" % pct))
    RAPPORT.write_text("\n".join(L) + "\n", encoding="utf-8")


def ecrire_ademe_js(nouveaux, version, nom_csv):
    meta = {"base": "Base Carbone® ADEME", "version": version,
            "extrait_le": datetime.date.today().isoformat(),
            "source": "data.gouv.fr — Base Carbone® (Licence Ouverte 2.0) — fichier " + nom_csv,
            "nombre_facteurs": len(nouveaux)}
    lignes = ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in nouveaux)
    contenu = ("// FICHIER GÉNÉRÉ par scripts/update_ademe.py — ne pas modifier à la main.\n"
               "// Chaque ligne = un facteur d'émission : l=libellé, c=catégorie, r/ri=rubrique, iu/il=unité de saisie, v=kgCO2e par unité.\n"
               "const ADEME_VERSION = " + json.dumps(meta, ensure_ascii=False) + ";\n"
               "const ADEME_RAW = [\n" + lignes + "\n];\n")
    ADEME_JS.write_text(contenu, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="export CSV de la Base Carbone ADEME")
    ap.add_argument("--version", required=True, help="nom de la version, ex. V23.7")
    ap.add_argument("--dry-run", action="store_true", help="n'écrit que le rapport")
    ap.add_argument("--max-suppressions-pct", type=float, default=15,
                    help="refuse d'écrire si plus de N %% des facteurs disparaissent (garde-fou, défaut 15)")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    lignes = lire_csv(args.csv)
    print("CSV lu : %d lignes" % len(lignes))
    nouveaux, rejets, ex_rej = convertir(lignes, cfg)
    anciens = charger_js(ADEME_JS, "ADEME_RAW")
    ajoutes, supprimes, modifies = comparer(anciens, nouveaux, cfg["seuil_alerte_variation_pct"])
    sans_dens, dens_obs = verifier_densites(nouveaux)
    ecrire_rapport(args, anciens, nouveaux, ajoutes, supprimes, modifies, rejets, ex_rej, sans_dens, dens_obs, cfg["seuil_alerte_variation_pct"])
    print("Avant %d → après %d | +%d −%d ~%d | rejetées %d | boissons sans densité %d"
          % (len(anciens), len(nouveaux), len(ajoutes), len(supprimes), len(modifies), sum(rejets.values()), len(sans_dens)))
    print("Rapport :", RAPPORT)

    if not nouveaux:
        sys.exit("ERREUR : aucun facteur retenu, rien n'est écrit. Vérifiez filtres et colonnes dans rubriques.json.")
    if anciens and len(supprimes) / len(anciens) * 100 > args.max_suppressions_pct:
        sys.exit("STOP : %.0f %% des facteurs actuels disparaîtraient (> %.0f %%). Lisez le rapport ; "
                 "si c'est normal, relancez avec --max-suppressions-pct 100." % (len(supprimes) / len(anciens) * 100, args.max_suppressions_pct))
    if args.dry_run:
        print("--dry-run : data/ademe.js non modifié."); return
    arch = RACINE / "data" / "archives"; arch.mkdir(exist_ok=True)
    shutil.copy2(ADEME_JS, arch / ("ademe_avant_%s.js" % datetime.date.today().isoformat()))
    ecrire_ademe_js(nouveaux, args.version, Path(args.csv).name)
    print("data/ademe.js mis à jour (ancien fichier sauvegardé dans data/archives/).")


if __name__ == "__main__":
    main()
