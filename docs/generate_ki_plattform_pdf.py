from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT_PATH = Path(__file__).with_name("KI_Plattform_Aufbau.pdf")

HM_RED = colors.HexColor("#E30613")
HM_RED_DARK = colors.HexColor("#B8000B")
INK = colors.HexColor("#161616")
MUTED = colors.HexColor("#61656F")
LINE = colors.HexColor("#DDDDDD")
SOFT_RED = colors.HexColor("#FFF1F2")
SOFT_GRAY = colors.HexColor("#F6F6F6")
GREEN = colors.HexColor("#1F9D55")
BLUE = colors.HexColor("#2F6FEB")


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=31,
            textColor=INK,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=22,
            textColor=INK,
            spaceBefore=4,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=HM_RED_DARK,
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.4,
            leading=13.4,
            textColor=INK,
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=11.5,
            textColor=MUTED,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=INK,
            spaceAfter=0,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.7,
            leading=11,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=11,
            textColor=INK,
        ),
        "table_cell_bold": ParagraphStyle(
            "TableCellBold",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=11,
            textColor=INK,
        ),
    }


class PlatformDiagram(Flowable):
    def __init__(self, width: float, height: float = 9.2 * cm):
        super().__init__()
        self.width = width
        self.height = height

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def draw_box(self, canvas, x, y, w, h, label, fill, stroke=LINE, text_color=INK):
        canvas.setFillColor(fill)
        canvas.setStrokeColor(stroke)
        canvas.roundRect(x, y, w, h, 8, stroke=1, fill=1)
        canvas.setFillColor(text_color)
        canvas.setFont("Helvetica-Bold", 8.5)
        lines = label.split("\n")
        line_height = 10
        start_y = y + h / 2 + (len(lines) - 1) * line_height / 2 - 3
        for i, line in enumerate(lines):
            canvas.drawCentredString(x + w / 2, start_y - i * line_height, line)

    def arrow(self, canvas, x1, y1, x2, y2):
        canvas.setStrokeColor(MUTED)
        canvas.setLineWidth(1.2)
        canvas.line(x1, y1, x2, y2)
        if x2 >= x1:
            canvas.line(x2, y2, x2 - 5, y2 + 3)
            canvas.line(x2, y2, x2 - 5, y2 - 3)
        else:
            canvas.line(x2, y2, x2 + 5, y2 + 3)
            canvas.line(x2, y2, x2 + 5, y2 - 3)

    def draw(self):
        c = self.canv
        w = self.width
        top = self.height - 0.4 * cm

        box_w = (w - 1.4 * cm) / 3
        box_h = 1.0 * cm
        x1 = 0
        x2 = box_w + 0.7 * cm
        x3 = 2 * (box_w + 0.7 * cm)

        self.draw_box(c, x1, top - box_h, box_w, box_h, "React UI\nChat + Profil", SOFT_RED, HM_RED)
        self.draw_box(c, x2, top - box_h, box_w, box_h, "FastAPI Backend\nAPI-Schicht", SOFT_GRAY, LINE)
        self.draw_box(c, x3, top - box_h, box_w, box_h, "Intent Router\nFlow-Auswahl", SOFT_RED, HM_RED)
        self.arrow(c, x1 + box_w, top - box_h / 2, x2, top - box_h / 2)
        self.arrow(c, x2 + box_w, top - box_h / 2, x3, top - box_h / 2)

        y_mid = top - 2.7 * cm
        branch_w = (w - 1.2 * cm) / 4
        gap = 0.4 * cm
        branches = [
            ("Wissensbasis\nRAG + pgvector", SOFT_GRAY, LINE),
            ("Studierendenprofil\nStatusdaten", SOFT_GRAY, LINE),
            ("Studienverlauf\nModule + ECTS", SOFT_GRAY, LINE),
            ("Eskalation\nFallback", SOFT_GRAY, LINE),
        ]
        for i, (label, fill, stroke) in enumerate(branches):
            x = i * (branch_w + gap)
            self.draw_box(c, x, y_mid, branch_w, box_h, label, fill, stroke)
            self.arrow(c, x3 + box_w / 2, top - box_h, x + branch_w / 2, y_mid + box_h)

        y_low = y_mid - 2.2 * cm
        self.draw_box(c, x1, y_low, box_w, box_h, "Gemini\nAntwortgenerator", colors.HexColor("#EEF4FF"), BLUE)
        self.draw_box(c, x2, y_low, box_w, box_h, "Supabase\nPostgres + Vector", colors.HexColor("#ECFDF3"), GREEN)
        self.draw_box(c, x3, y_low, box_w, box_h, "Quellen + Route\nsichtbar in UI", SOFT_RED, HM_RED)

        self.arrow(c, x1 + box_w, y_low + box_h / 2, x2, y_low + box_h / 2)
        self.arrow(c, x2 + box_w, y_low + box_h / 2, x3, y_low + box_h / 2)

        c.setStrokeColor(LINE)
        c.setLineWidth(0.8)
        c.roundRect(0, 0, w, self.height, 10, stroke=1, fill=0)


class RouteDiagram(Flowable):
    def __init__(self, width: float, height: float = 6.4 * cm):
        super().__init__()
        self.width = width
        self.height = height

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def draw_box(self, canvas, x, y, w, h, label, fill, stroke):
        canvas.setFillColor(fill)
        canvas.setStrokeColor(stroke)
        canvas.roundRect(x, y, w, h, 7, stroke=1, fill=1)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 8.3)
        for i, line in enumerate(label.split("\n")):
            canvas.drawCentredString(x + w / 2, y + h / 2 + 5 - i * 10, line)

    def arrow(self, canvas, x1, y1, x2, y2):
        canvas.setStrokeColor(MUTED)
        canvas.line(x1, y1, x2, y2)
        canvas.line(x2, y2, x2 - 4, y2 + 3)
        canvas.line(x2, y2, x2 - 4, y2 - 3)

    def draw(self):
        c = self.canv
        w = self.width
        center_w = 4.1 * cm
        x_center = (w - center_w) / 2
        top_y = self.height - 1.1 * cm

        self.draw_box(c, x_center, top_y, center_w, 0.9 * cm, "Nutzerfrage", SOFT_RED, HM_RED)
        self.draw_box(c, x_center, top_y - 1.5 * cm, center_w, 0.9 * cm, "Intent Router", SOFT_GRAY, LINE)
        self.arrow(c, x_center + center_w / 2, top_y, x_center + center_w / 2, top_y - 0.6 * cm)

        route_w = (w - 1.2 * cm) / 4
        gap = 0.4 * cm
        y = 0.7 * cm
        routes = [
            ("Regel/Frist\nWissensbasis", colors.HexColor("#F8FAFC"), LINE),
            ("Persönlicher Status\nProfil", colors.HexColor("#F8FAFC"), LINE),
            ("Beratung\nStudienverlauf", colors.HexColor("#F8FAFC"), LINE),
            ("Unklar\nEskalation", colors.HexColor("#FFF1F2"), HM_RED),
        ]
        for i, (label, fill, stroke) in enumerate(routes):
            x = i * (route_w + gap)
            self.draw_box(c, x, y, route_w, 1.1 * cm, label, fill, stroke)
            self.arrow(c, x_center + center_w / 2, top_y - 1.5 * cm, x + route_w / 2, y + 1.1 * cm)


def para(text: str, style):
    return Paragraph(text, style)


def bullet_items(items: list[str], styles):
    return [para(f"• {item}", styles["body"]) for item in items]


def table(data, col_widths, styles):
    normalized = []
    for row_index, row in enumerate(data):
        style = styles["table_header"] if row_index == 0 else styles["table_cell"]
        normalized.append([para(cell, style) for cell in row])
    result = Table(normalized, colWidths=col_widths, hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HM_RED),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ]
        )
    )
    return result


def add_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(HM_RED)
    canvas.setLineWidth(1.2)
    canvas.line(doc.leftMargin, A4[1] - 1.3 * cm, A4[0] - doc.rightMargin, A4[1] - 1.3 * cm)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(HM_RED)
    canvas.drawString(doc.leftMargin, A4[1] - 1.05 * cm, "HM Smart University")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - doc.rightMargin, 0.85 * cm, f"Seite {doc.page}")
    canvas.restoreState()


def build_pdf():
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        rightMargin=1.7 * cm,
        leftMargin=1.7 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.5 * cm,
        title="Aufbau der KI-Serviceplattform",
    )

    content = []

    content.append(Spacer(1, 1.1 * cm))
    content.append(para("KI-Serviceplattform der Smart University", styles["title"]))
    content.append(
        para(
            "Technischer Überblick für Nicht-Entwickler: Komponenten, Datenquellen, Routing und MVP-Stand",
            styles["subtitle"],
        )
    )
    content.append(Spacer(1, 0.2 * cm))
    content.append(
        table(
            [
                ["Kurzfassung", "Bedeutung"],
                [
                    "Was ist die Plattform?",
                    "Ein zentraler KI-Servicebot, der Standardfragen beantwortet und erste personalisierte Studienberatung ermöglicht.",
                ],
                [
                    "Was ist der aktuelle Stand?",
                    "MVP 1 bis MVP 3 sind umgesetzt: RAG-Wissensbasis, Profil-/Studienverlaufsdaten und Intent Router.",
                ],
                [
                    "Warum ist das relevant?",
                    "Die Plattform verbindet den Studierendenservice mit der individuellen Studienberatung und bildet damit zwei Problembereiche der Smart-Uni-Fallstudie ab.",
                ],
            ],
            [4.0 * cm, 12.2 * cm],
            styles,
        )
    )
    content.append(Spacer(1, 0.6 * cm))
    content.append(
        para(
            "<b>Leitidee:</b> Der Servicebot ist nicht nur ein FAQ-Chatbot, sondern der erste Baustein einer modularen KI-Serviceplattform.",
            styles["callout"],
        )
    )

    content.append(PageBreak())

    content.append(para("1. Zielbild der Plattform", styles["h1"]))
    content.append(
        para(
            "Die Plattform soll eine digitale Anlaufstelle für Studierende schaffen. Sie beantwortet wiederkehrende Servicefragen, nutzt strukturierte Profildaten für persönliche Statusauskünfte und kann schrittweise zur individuellen Studienberatung ausgebaut werden.",
            styles["body"],
        )
    )
    content.extend(
        bullet_items(
            [
                "<b>Schnelle Standardantworten:</b> Fristen, Rückmeldung, Prüfungsabmeldung und Studierendenausweis.",
                "<b>Personalisierung:</b> Antworten können ECTS, Semesterbeitrag, Studiengang und Studienverlauf berücksichtigen.",
                "<b>Kontrollierte KI:</b> Antworten kommen nur aus verifizierter Wissensbasis und strukturierten Profil-/Verlaufsdaten.",
                "<b>Ausbaubar:</b> Später können echte CRM-Daten, Betreuerkapazitäten und Empfehlungen ergänzt werden.",
            ],
            styles,
        )
    )
    content.append(Spacer(1, 0.35 * cm))
    content.append(para("Architekturüberblick", styles["h2"]))
    content.append(PlatformDiagram(width=16.2 * cm))

    content.append(PageBreak())

    content.append(para("2. Zentrale Komponenten", styles["h1"]))
    content.append(
        table(
            [
                ["Komponente", "Aufgabe", "Aktueller MVP-Stand"],
                [
                    "React UI",
                    "Chat-Oberfläche mit gespeicherten Gesprächen, Quellenanzeige, Route-Anzeige und rechtem Kontextbereich.",
                    "Umgesetzt",
                ],
                [
                    "FastAPI Backend",
                    "Nimmt Fragen entgegen, ruft Datenquellen ab und gibt strukturierte Antworten an die UI zurück.",
                    "Umgesetzt",
                ],
                [
                    "Intent Router",
                    "Entscheidet, ob die Frage über Wissensbasis, Profilstatus, Studienberatung oder Eskalation beantwortet wird.",
                    "MVP 3 umgesetzt",
                ],
                [
                    "RAG-Wissensbasis",
                    "Speichert offizielle Regeln als Vektoren und liefert passende Kontext-Chunks.",
                    "MVP 1 umgesetzt",
                ],
                [
                    "Studierendenprofil",
                    "Enthält persönliche Statusdaten wie ECTS, Semester, Semesterbeitrag und Bachelorarbeitsstatus.",
                    "MVP 2 umgesetzt",
                ],
                [
                    "Studienverlauf",
                    "Enthält bestandene und offene Module sowie Interessen für erste Beratungslogik.",
                    "MVP 2 umgesetzt",
                ],
                [
                    "Gemini",
                    "Generiert freie Antworten aus bereitgestelltem Kontext. Pitch-kritische FAQ-Fragen sind zusätzlich stabil regelbasiert abgefangen.",
                    "Eingebunden",
                ],
            ],
            [3.5 * cm, 8.2 * cm, 4.5 * cm],
            styles,
        )
    )

    content.append(PageBreak())

    content.append(para("3. Wie eine Anfrage verarbeitet wird", styles["h1"]))
    content.append(
        para(
            "Der wichtigste neue Baustein ist der Intent Router. Er entscheidet zuerst, welcher Flow zuständig ist. Dadurch wird verhindert, dass jede Frage blind an das Sprachmodell geschickt wird.",
            styles["body"],
        )
    )
    content.append(RouteDiagram(width=16.2 * cm))
    content.append(Spacer(1, 0.35 * cm))
    content.append(
        table(
            [
                ["Beispielfrage", "Route", "Genutzte Daten"],
                [
                    "Bis wann muss ich mich zurückmelden?",
                    "Wissensbasis",
                    "RAG-Dokumente / Rückmeldeordnung",
                ],
                [
                    "Wie viele ECTS habe ich derzeit?",
                    "Profilstatus",
                    "Studierendenprofil",
                ],
                [
                    "Kann ich meine Bachelorarbeit anmelden?",
                    "Studienberatung",
                    "Prüfungsordnung + ECTS + offene Module",
                ],
                [
                    "Wie viel kostet das Fach Marketing?",
                    "Eskalation",
                    "Keine verifizierte Quelle, daher Fallback",
                ],
            ],
            [6.3 * cm, 3.5 * cm, 6.4 * cm],
            styles,
        )
    )

    content.append(PageBreak())

    content.append(para("4. Datenquellen und Governance", styles["h1"]))
    content.append(
        para(
            "Die Plattform trennt bewusst zwischen offizieller Wissensbasis und personenbezogenen Studierendendaten. Diese Trennung ist fachlich wichtig, weil allgemeine Regeln und individuelle Statusdaten unterschiedliche Risiken haben.",
            styles["body"],
        )
    )
    content.append(
        table(
            [
                ["Datenquelle", "Beispiele", "Warum getrennt?"],
                [
                    "Wissensbasis",
                    "FAQ, Prüfungsordnung, Rückmeldefristen, Studierendenausweis-Regeln",
                    "Diese Daten sind offiziell und können für alle Studierenden gleich genutzt werden.",
                ],
                [
                    "Studierendenprofil",
                    "Name, Studiengang, Semester, ECTS, Semesterbeitrag",
                    "Diese Daten sind personenbezogen und müssen später über Auth/RLS geschützt werden.",
                ],
                [
                    "Studienverlauf",
                    "Bestandene Module, offene Pflichtmodule, Interessen",
                    "Diese Daten ermöglichen Beratung, dürfen aber nicht mit fremden Profilen vermischt werden.",
                ],
                [
                    "Chatverlauf",
                    "Gespeicherte Gespräche, Titel, Nachrichten",
                    "Speicherung ist optional; Löschen anonymisiert Inhalte.",
                ],
            ],
            [3.6 * cm, 6.2 * cm, 6.4 * cm],
            styles,
        )
    )
    content.append(Spacer(1, 0.35 * cm))
    content.append(para("Aktuelle Schutzmechanismen im Prototyp", styles["h2"]))
    content.extend(
        bullet_items(
            [
                "Geschlossene Wissensbasis: keine freien Behauptungen ohne Kontext.",
                "Fallback: Wenn keine verifizierte Route oder Quelle gefunden wird, verweist der Bot an das Studierendensekretariat.",
                "Quellenanzeige: Antworten zeigen, welche Quelle verwendet wurde.",
                "Optionale Chat-Speicherung: Nutzer können Chatverlauf deaktivieren; Löschen anonymisiert Inhalte.",
            ],
            styles,
        )
    )

    content.append(PageBreak())

    content.append(para("5. MVP-Stand und nächste Ausbaustufe", styles["h1"]))
    content.append(
        table(
            [
                ["MVP", "Inhalt", "Status"],
                [
                    "MVP 1",
                    "RAG-Studierendenservice: Wissensbasis, Quellen, Fallback, Standardfragen.",
                    "Abgehakt",
                ],
                [
                    "MVP 2",
                    "Personalisierung: Profil, ECTS, Semesterbeitrag, Studienverlauf, offene Module.",
                    "Abgehakt",
                ],
                [
                    "MVP 3",
                    "Intent Router: explizite Entscheidung zwischen Wissensbasis, Profilstatus, Studienberatung und Eskalation.",
                    "Abgehakt",
                ],
                [
                    "MVP 4",
                    "Regelbasierte Studienberatung: Empfehlungen für nächste Schritte, fehlende Module, Schwerpunkt und Bachelorarbeit.",
                    "Nächster Schritt",
                ],
            ],
            [2.6 * cm, 10.0 * cm, 3.6 * cm],
            styles,
        )
    )
    content.append(Spacer(1, 0.35 * cm))
    content.append(para("Was MVP 4 ergänzen würde", styles["h2"]))
    content.extend(
        bullet_items(
            [
                "Eine eigene Beratungslogik statt einzelner Spezialfälle.",
                "Regeln wie: Bachelorarbeit ab 120 ECTS, offene Pflichtmodule, passende Schwerpunktvorschläge.",
                "Eine nachvollziehbare Begründung: Der Bot erklärt, welche Profil- und Verlaufsdaten zur Empfehlung geführt haben.",
                "Später: echte Tabellen für Module, Betreuer, Abschlussarbeitsthemen und Kapazitäten.",
            ],
            styles,
        )
    )

    doc.build(content, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(build_pdf())
