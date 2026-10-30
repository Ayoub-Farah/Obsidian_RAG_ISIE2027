"""Build the French PDF from the independently fitted PTP distance dataset."""
from pathlib import Path
import json
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/ptp_report_deps"))
sys.path.insert(0, str(ROOT / 'tools'))
from report_paths import resolve_report_path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak

REPORT = ROOT / "reports/ptp_distance_model_20261029"
SOURCE = ROOT / "reports/ptp_scope_20261029T160956Z"
WIDTH = 17.4 * cm
NAVY, TEAL = colors.HexColor("#17324d"), colors.HexColor("#00858b")


def build(report=REPORT, source=SOURCE, output=ROOT/'build/report_outputs/ptp_distance_pdf'):
    report=resolve_report_path(Path(report).resolve())
    source=resolve_report_path(Path(source).resolve())
    output=Path(output).resolve()
    (output/'figures').mkdir(parents=True,exist_ok=True)
    fonts = Path(matplotlib.get_data_path()) / "fonts/ttf"
    for name, filename in (("DV", "DejaVuSans.ttf"), ("DVB", "DejaVuSans-Bold.ttf"), ("DVM", "DejaVuSansMono.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DV", boldItalic="DVB")
    fit = json.loads((report / "fit_results.json").read_text(encoding="utf-8"))
    model = json.loads((report / "model_parameters.json").read_text(encoding="utf-8"))
    params, points = model["parameters"], fit["measurements"]
    assert len(points) == 9 and all(p["n"] == 100 for p in points)
    styles = getSampleStyleSheet()
    for name, font, size, leading, color in (
        ("BodyFR", "DV", 9.4, 13.3, NAVY), ("TitleFR", "DVB", 24, 29, NAVY),
        ("HeadingFR", "DVB", 15, 20, TEAL), ("SmallFR", "DV", 7.7, 10.5, colors.HexColor("#526274")),
        ("CodeFR", "DVM", 7.1, 10.2, NAVY), ("LeadFR", "DV", 11, 15.5, NAVY)):
        styles.add(ParagraphStyle(name=name, fontName=font, fontSize=size, leading=leading,
                                  textColor=color, spaceAfter=9 if size > 12 else 7))
    story = []

    def p(text, style="BodyFR"):
        story.append(Paragraph(text, styles[style]))

    def heading(text):
        p(text, "HeadingFR")

    def page():
        story.append(PageBreak())

    def picture(path, width=WIDTH, maximum_height=None):
        with PILImage.open(path) as im:
            w, h = im.size
        height = width * h / w
        if maximum_height is not None and height > maximum_height:
            width *= maximum_height / height
            height = maximum_height
        story.append(Image(str(path), width=width, height=height))
        story.append(Spacer(1, 7))

    def equation(name, expression):
        dest = output / "figures" / f"equation_{name}.png"
        fig = plt.figure(figsize=(9, .65))
        fig.text(.01, .5, "$" + expression + "$", fontsize=16, va="center", color="#17324d")
        fig.savefig(dest, dpi=240, bbox_inches="tight", pad_inches=.08, facecolor="white")
        plt.close(fig)
        picture(dest, maximum_height=1.35 * cm)

    def table(rows, widths):
        body = [[Paragraph(str(cell), styles["SmallFR"]) for cell in row] for row in rows]
        t = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3f0f1")),
            ("LINEBELOW", (0, 0), (-1, 0), .8, TEAL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f9")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t); story.append(Spacer(1, 9))

    def code(lines):
        p("<br/>".join(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                      for line in lines), "CodeFR")

    # 1 - Question and findings.
    p("Synchronisation PTP<br/>Décalage et jitter selon la distance", "TitleFR")
    p("Rapport d'essai, modèle théorique et paramètres de simulation<br/>Anneau N=9 - campagne du 29 octobre 2026", "LeadFR")
    p("<b>Question étudiée.</b> Comment évoluent le décalage moyen et la dispersion des impulsions lorsque l'on s'éloigne de M1 sur le chemin de synchronisation ? Le nombre total de moteurs reste fixé à neuf ; la distance varie de zéro à huit sauts.")
    table([
        ["Constat", "Résultat principal"],
        ["Même FPGA : M1 à M3", "Dispersion proche de la calibration, environ 0,04 ns. Ce chiffre décrit la mesure différentielle ; ce n'est pas une exactitude absolue de 40 ps."],
        ["Autres FPGA : M4 à M9", "Écarts-types de 4,49 à 6,19 ns. Les biais changent de signe d'une frontière à l'autre ; la moyenne n'augmente pas régulièrement avec la distance."],
        ["Excursions rares", "Trois captures conditionnelles sur M7 confirment -67,98 ns, +57,16 ns et -58,66 ns. Leur fréquence n'a pas été identifiée."],
    ], [4.4 * cm, 13 * cm])
    heading("Chemin réellement utilisé")
    p("<b>M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9</b><br/>A : M1-M3 ; B : M4-M6 ; C : M7-M9. Les passages optiques du chemin de phase sont M3→M4 et M6→M7. La fermeture physique C→A ne fait pas de M9 un voisin de phase à un saut de M1 : elle sert notamment au retour ARM [R2].")
    equation("distance", r"h=i-1,\quad n_{\mathrm{chemin}}=h+1,\quad p(h)=\lfloor h/3\rfloor,\quad v(h)=h-p(h)")
    p("h compte tous les sauts ; p compte les traversées entre horloges physiques ; v compte les liens internes au FPGA. Les courbes principales utilisent h, conformément à la question de distance depuis M1.")
    p("<b>Conclusion.</b> Un modèle réduit doit distinguer les traversées physiques, le bruit partagé entre moteurs d'une même carte et une composante d'excursions. Une simple loi universelle en √h manquerait les paliers et les queues observés.")

    # 2 - Test conditions and all values.
    page(); heading("1. Conditions d'essai et résultats numériques")
    table([
        ["Élément", "Condition de la campagne"],
        ["FPGA et configuration", "A=OBS001A, B=OBS003A, C=OBS002A ; image K=3 ; N=9 ; run_id=9 ; config_id=b548f1927173517b. Aucun rechargement ni changement RTL pendant les acquisitions."],
        ["Cadences", "Tick logique nominal 16 ns ; période des marqueurs 100 µs ; largeur 1,024 µs ; maintenance nominale 1 ms. Dérive, jitter et perte artificiels configurés à zéro."],
        ["Oscilloscope", "RIGOL MHO984, firmware 00.01.00 ; acquisition NORM sans moyennage ; 2 Géch/s réellement relus ; pas ADC 0,5 ns ; BYTE/RAW ; entrées 1 MΩ et facteur de sonde ×10 ; bande non limitée."],
        ["Sondes et sélection", "CH1 fixe sur TEST_SYNC de A. CH2 sur MOSI de la carte étudiée. Sorties vérifiées par désactivation/réactivation. Sélection logicielle locale, sans arrêter le PTP."],
        ["Échantillons", "100 captures SINGLE neuves par module, plus 100 de calibration. Les fenêtres de persistance de 20 s sont archivées séparément. Mémoire principale 10k/5 µs ; calibration 100k/50 µs au même débit."],
    ], [3.4 * cm, 14 * cm])
    p("Δ = front OBS - front REF : un délai négatif est une impulsion observée en avance. La colonne μ corr. retire seulement le biais moyen des sondes/voies, -0,29667 ns. Les différences de chemins GPIO entre cartes restent comprises dans les biais.")
    rows = [["Module", "h / p", "μ corr. (ns)", "σ (ns)", "Min. brut (ns)", "Max. brut (ns)"]]
    for row in points:
        rows.append([f"M{row['module']} / {row['board']}", f"{row['h']} / {row['p']}",
                     f"{row['mean_corrected_ns']:+.3f}", f"{row['sample_sd_ns']:.3f}",
                     f"{row['min_raw_ns']:+.3f}", f"{row['max_raw_ns']:+.3f}"])
    table(rows, [2.6 * cm, 1.6 * cm, 3.3 * cm, 2.8 * cm, 3.5 * cm, 3.6 * cm])
    p("σ est l'écart-type d'échantillon des 100 délais, et non le RMS ni une borne maximale. Les extrema de ce tableau ne concernent que ces 100 captures. Les séries initiales non qualifiées ont été conservées comme diagnostics et exclues de l'ajustement [R1].", "SmallFR")

    # 3 - Main distance curves.
    page(); heading("2. Courbes selon le nombre de sauts depuis M1")
    picture(report / "figures/distance_offset_jitter.png", maximum_height=18 * cm)
    p("<b>Lecture.</b> Les frontières physiques se situent entre h=2 et h=3, puis entre h=5 et h=6. Sur A, ajouter deux moteurs virtuels au même domaine d'horloge n'ajoute pas de dispersion résolue. Sur B et C, le bruit inter-horloges domine la mesure.")
    p("Le biais moyen n'est pas monotone : la contribution effective de la seconde frontière compense une partie de la première. Les moteurs ont été mesurés successivement ; cette campagne ne sépare pas totalement un effet de position d'une variation lente dans le temps.")
    p("Les barres indiquent des écarts-types observés, pas des intervalles de confiance sur la moyenne. Les neuf positions appartiennent à une configuration N=9 ; elles ne constituent pas neuf tailles d'anneau différentes.", "SmallFR")

    # 4 - Mechanistic theory.
    page(); heading("3. Équations théoriques et lien avec le RTL")
    p("L'échange à quatre horodatages estime l'avance de l'horloge enfant sur son parent. Le RTL applique la correction avec un gain unitaire [R2, R4] :")
    equation("theta", r"\widehat\theta_i=\frac{(t_2-t_1)-(t_4-t_3)}{2},\qquad c_i^+=c_i^- -\widehat\theta_i")
    p("En notant e l'avance enfant-parent, d→ et d← les délais effectifs dans les deux sens et ν les erreurs effectives de datation d'événements :")
    equation("local", r"\widehat\theta_i\simeq e_i+\frac{d_i^{\rightarrow}-d_i^{\leftarrow}}{2}+\eta_i,\qquad\eta_i=\frac{\nu_2-\nu_1-\nu_4+\nu_3}{2}")
    p("Après correction, la contribution au retard d'impulsion enfant-parent a le signe +(d→-d←)/2 + η. Une erreur d'horloge positive et un retard d'impulsion positif ont des signes opposés. Un modèle de cascade approché s'écrit :")
    equation("cascade", r"\Delta_h(t)\simeq b+\sum_{k=1}^{h}a_k+\sum_{k=1}^{h}\xi_k(t)+J_h(t)")
    p("a regroupe le biais effectif par lien, notamment l'asymétrie ; ξ regroupe bruit, dérive résiduelle et effet de l'âge de correction ; J décrit les excursions. Dans le système réel, le parent est observé avec un retard et les corrections sont différées jusqu'à la fin des transactions : cette somme décrit un régime réduit, pas toute la dynamique du servo.")
    equation("covariance", r"\mathrm{Var}(\Delta_h)=\sigma_m^2+\sum_{k=1}^{h}\mathrm{Var}(\xi_k)+2\sum_{k<\ell}\mathrm{Cov}(\xi_k,\xi_\ell)+\mathrm{Var}(J_h)+\cdots")
    p("La loi en √h ne découle de cette expression que si les incréments sont homogènes et indépendants. Sur un même FPGA, le partage de l'horloge corrèle les erreurs et peut les annuler. Les acquisitions successives n'identifient pas les covariances entre modules.")
    equation("quantizer", r"\mathrm{Var}(\eta)=w^T\Sigma_\nu w,\quad w=\frac{1}{2}(-1,1,1,-1)^T;\qquad\sigma_{\eta,\mathrm{iid}}=q/\sqrt{12}")
    p("Avec quatre erreurs uniformes indépendantes de largeur q=16 ns, l'ordre de grandeur est 4,619 ns. C'est une hypothèse de phase effective, pas une description exacte des horodatages : ceux du RTL sont en Q48.16. Les 16 ns sont la grille physique des événements et des fronts, non leur LSB numérique. Cette comparaison ne prouve ni indépendance ni mécanisme causal.", "SmallFR")

    # 5 - Calibration and model selection.
    page(); heading("4. Modèle ajusté à cette expérience")
    a0 = params["baseline_phase_ns"]; a1, a2 = params["boundary_bias_ns"]
    sm = params["measurement_sigma_ns"]; sp = params["physical_sigma_ns"]
    equation("mean_fit", rf"\mu(h)\simeq {a0:.6f}{a1:+.6f}\,\mathbf{{1}}_{{h\geq3}}{a2:+.6f}\,\mathbf{{1}}_{{h\geq6}}\quad[\mathrm{{ns}}]")
    equation("sigma_fit", rf"\sigma(h)\simeq\sqrt{{{sm:.5f}^2+{sp*sp:.5f}\,\lfloor h/3\rfloor}}\quad[\mathrm{{ns}}],\qquad0\leq h\leq8")
    p("La moyenne est un ajustement descriptif par deux frontières distinctes. Le modèle de variance réduit suppose des incréments physiques indépendants et fixe la contribution virtuelle à zéro par parcimonie, dans ce profil sans dérive virtuelle. Cette contribution n'est pas identifiée comme intrinsèquement nulle.")
    mean_models = fit["mean_models"]; vm = fit["variance_models"]
    table([
        ["Comparaison", "Loi naïve en h", "Modèle retenu par frontières"],
        ["RMSE de moyenne", f"{mean_models['naive_linear']['rmse_ns']:.3f} ns", f"{mean_models['board_step']['rmse_ns']:.3f} ns"],
        ["RMSE moyenne, retrait d'un module", f"{mean_models['naive_linear']['loo_rmse_ns']:.3f} ns", f"{mean_models['board_step']['loo_rmse_ns']:.3f} ns"],
        ["RMSE des écarts-types", f"{vm['qh']['rmse_sd_ns']:.3f} ns", f"{vm['qp_parsimonious']['rmse_sd_ns']:.3f} ns"],
    ], [6.5 * cm, 5.2 * cm, 5.7 * cm])
    p("La comparaison graphique détaillée figure dans l'annexe, en grand format.", "SmallFR")
    p("Ajouter une pente virtuelle libre améliore peu l'interpolation et donne une pente très sensible à la pondération. Le choix retenu sépare les frontières physiques et évite d'affirmer un coût universel par saut virtuel.", "SmallFR")
    table([
        ["Paramètre du modèle central", "Valeur", "Interprétation"],
        ["σ mesure", f"{sm:.5f} ns", "Calibration différentielle des voies et sondes."],
        ["σ physique", f"{sp:.5f} ns", "Incrément effectif par frontière, sous hypothèse d'indépendance."],
        ["σ virtuel", "0 ns dans le modèle", "Choix réduit du profil nominal ; pas une limite intrinsèque mesurée."],
        ["Biais A→B / B→C", f"{a1:+.3f} / {a2:+.3f} ns", "Contrastes effectifs, hétérogènes ; ne pas répéter automatiquement."],
        ["Probabilité des excursions", "Non identifiée", "Aucune calibration de fréquence à partir des trois captures ciblées."],
    ], [5.5 * cm, 4.3 * cm, 7.6 * cm])
    ci = fit["bootstrap_iid"]["intervals"]["physical_sigma_ns"]
    p(f"Sensibilité statistique : un bootstrap iid de 5 000 réplications donne σ physique entre {ci['lower']:.2f} et {ci['upper']:.2f} ns à 95 %. Cet intervalle est conditionnel à l'hypothèse iid ; il ne couvre pas la corrélation temporelle, un nouveau démarrage, de nouvelles cartes, les queues ou l'exactitude absolue de l'instrument.", "SmallFR")

    # 6 - Rare events.
    page(); heading("5. Excursions : une composante séparée")
    picture(source / "outliers_confirmes.png", maximum_height=6.3 * cm)
    p("Ces trois acquisitions conditionnelles de M7 dépassent la fenêtre relue d'environ [-50 ; +50] ns. Elles confirment des excursions que les 100 captures ordinaires de ce module n'ont pas échantillonnées. Elles restent exclues de l'ajustement central et ne mesurent pas un taux d'apparition.")
    equation("tail", r"\Delta_h=\mu_h+X_h+Z_hA_h,\qquad P(Z_h=1)=\pi_h\quad\mathrm{non\ identifiee}")
    p("X représente la composante centrale ajustée. π, la loi d'amplitude et la propagation temporelle des excursions restent à mesurer. Les valeurs -67,98/+57,16/-58,66 ns sont des délais absolus, pas des incréments à additionner directement à μ : pour un scénario d'injection, centrer l'amplitude par rapport au biais choisi.")
    p("<b>Éléments du RTL compatibles avec des queues.</b> Le mode externe utilisé ne rejette pas directement toute correction |θ| &gt; 64 ns. Son filtre actif porte sur le délai aller-retour ; une variation différentielle peut laisser ce délai presque inchangé. Le gain unitaire et l'application différée peuvent aussi corréler les erreurs en cascade [R2, R3]. Ces éléments ne démontrent pas la cause des trois événements capturés.")
    p("Une simulation uniquement gaussienne, ou une borne tirée de trois fois σ, ne représente donc pas toute la synchronisation observée. Les études de sensibilité doivent annoncer la probabilité de queue choisie ; elle n'est pas un paramètre calibré de cette expérience.")
    p("<b>Mesures complémentaires utiles.</b> Comptage continu du temps réellement armé et des dépassements, captures longues des transitions, répétitions après redémarrage, retour régulier à un même module pour séparer dérive lente et distance, puis acquisition simultanée de plusieurs sorties pour estimer les covariances.")

    # 7 - Conditional extrapolation.
    page(); heading("6. Extrapolation : l'architecture fait partie de l'équation")
    picture(report / "figures/extrapolation_scenarios.png", maximum_height=10.6 * cm)
    p("Ces courbes sont des <b>scénarios du modèle central</b>, sans queues. Le seul nombre total de moteurs mesuré est N=9. Le point M9 est une observation ; les autres tailles ne sont pas une nouvelle campagne expérimentale.")
    p("• Une horloge physique par module : p=N-1, d'où σ ≈ 4,38√(N-1) ns hors bruit de mesure.<br/>• Trois modules par FPGA et ajout de FPGA : p=⌊(N-1)/3⌋.<br/>• Trois FPGA fixes et davantage de moteurs par FPGA : p=2 au dernier moteur, sous l'hypothèse virtuelle nulle, soit environ 6,19 ns.")
    p("Le dernier scénario ne démontre pas la faisabilité en ressources : l'image K=3 ne porte pas plus de neuf moteurs. Il suppose une autre capacité et ne couvre pas de nouvelles files d'attente, dérives virtuelles indépendantes, corrélations ou excursions.")
    p("<b>Biais des nouveaux liens.</b> Les deux biais mesurés sont hétérogènes. Le modèle ne peut pas prévoir la moyenne d'une troisième frontière sans hypothèse ou donnée supplémentaire. La bibliothèque refuse de répéter silencieusement les deux biais connus.")

    # 8 - Practical use and references.
    page(); heading("7. Utilisation dans les simulations et traçabilité")
    p("Le fichier <b>model_parameters.json</b> contient les paramètres, le domaine validé, les hypothèses et une probabilité d'excursion laissée à null. Le module <b>tools/ptp_distance_model.py</b> calcule les moments et fournit un échantillonneur de chaîne avec incréments partagés par préfixe.")
    code([
        "from tools.ptp_distance_model import load_parameters, predict, sample_chain",
        "p = load_parameters('reports/ptp_distance_model_20261029/model_parameters.json')",
        "m = predict(8, 2, p, include_measurement=False)",
        "x = sample_chain([0,0,0,1,1,1,2,2,2], 10000, p, seed=20261029)",
    ])
    p("La loi uniforme des incréments de l'échantillonneur est un choix de modèle compatible avec les moments ajustés, pas une distribution identifiée de chaque lien. Les moteurs d'un même domaine partagent les erreurs amont ; le bruit instrumental est optionnel et n'est pas ajouté par défaut à la simulation physique.")
    p("<b>Éviter le double comptage.</b> Dans une simulation RTL qui reproduit déjà horloges, horodatages, échanges, servo et génération des fronts, ne pas ajouter automatiquement ce bruit en sortie. Utiliser le modèle réduit comme référence de comparaison, ou injecter les incertitudes physiques manquantes au niveau approprié. Les deux usages sont distincts.")
    code([
        "py -3 scripts/fit_ptp_distance_model.py --source reports/ptp_scope_20261029T160956Z",
        "    --output build/report_outputs/ptp_distance_model",
        "py -3 scripts/build_ptp_distance_report.py",
        "py -3 -m unittest sim.test_ptp_distance_model",
    ])
    p("Les deux lignes du premier appel forment une seule commande. La génération PDF utilise reportlab et pypdf dans build/ptp_report_deps ; les calculs utilisent NumPy, SciPy et Matplotlib. Les captures d'origine ne sont ni modifiées ni réacquises pour ce rapport.", "SmallFR")
    heading("Références et preuves")
    p("[R1] Campagne locale ptp_scope_20261029T160956Z : 900 captures de modules, 100 de calibration, trois excursions conditionnelles ; commit source 27e03fd, manifestes SHA-256 et journaux conservés.<br/>[R2] rtl/sync/sync_system.vhd, lignes 137-180 et 193-199 ; rtl/sync/management_codec.vhd, lignes 80-91 et 120-123 : route, quatre horodatages, correction et retour ARM.<br/>[R3] rtl/system/ptp_emulation_core.vhd, activation du mode externe ; theory_audit.json : empreintes et qualification détaillée des équations.<br/>[R4] J. Eidson, Tutorial on IEEE 1588, 10 octobre 2005, pages 20-24, document hébergé par NIST : <link href='https://www.nist.gov/system/files/documents/el/isd/ieee/tutorial-basic.pdf' color='#00858b'>nist.gov/.../tutorial-basic.pdf</link>. Référence pédagogique de l'échange à quatre horodatages.<br/>[R5] RIGOL, guide de programmation MHO900 : <link href='https://www.rigol.com/dam/global/downloads/brochures/en/program-guide/oscilloscopes/MHO900-ProgrammingGuide.pdf?t=1760543891885' color='#00858b'>guide officiel</link> ; réglages réellement relus archivés dans la campagne.", "SmallFR")

    page(); heading("Annexe. Comparaison graphique des modèles")
    picture(report / "figures/model_comparison.png", maximum_height=20.5 * cm)
    p("La droite en h attribue un bruit à chaque saut logique ; le modèle par frontières p distingue les domaines physiques. Les deux ajustements sont faits sur les mêmes données. Leur comparaison ne constitue pas une validation sur de nouvelles cartes.", "SmallFR")

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(TEAL); canvas.setLineWidth(.7)
        canvas.line(doc.leftMargin, 808, doc.leftMargin + WIDTH, 808)
        canvas.setFont("DV", 8); canvas.setFillColor(NAVY)
        canvas.drawString(doc.leftMargin, 816, "Obsidian_RAG / Synchronisation PTP")
        canvas.drawRightString(doc.leftMargin + WIDTH, 816, "N=9 | 29/10/2026")
        canvas.setFont("DV", 7.5)
        canvas.drawString(doc.leftMargin, 28, "Mesures, modèle ajusté et extrapolations conditionnelles")
        canvas.drawRightString(doc.leftMargin + WIDTH, 28, f"Page {doc.page}")
        canvas.restoreState()

    destination = output / "Rapport_PTP_distance_modele.pdf"
    document = SimpleDocTemplate(str(destination), pagesize=(21 * cm, 29.7 * cm),
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.5 * cm,
        title="Synchronisation PTP selon la distance - mesures et modèle", author="Obsidian_RAG")
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    print(destination)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=REPORT)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=ROOT/'build/report_outputs/ptp_distance_pdf')
    args=parser.parse_args()
    build(args.report,args.source,args.output)
