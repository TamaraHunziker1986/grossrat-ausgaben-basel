"""Hauptthemen für Vorstösse und Abstimmungen.

Jedes Geschäft bekommt genau ein Hauptthema. Grundlage ist der Titel und, wo vorhanden,
das Thema, das der Parlamentsdienst vergeben hat (zählt dreifach). Gewinnt das Thema mit
den meisten Treffern; bei Gleichstand das weiter oben aufgeführte.

Stichworte sind reguläre Ausdrücke und werden auf den kleingeschriebenen Text angewendet.
Wer ein Stichwort ergänzt, sollte danach pruefliste.md anschauen.
"""
import re

THEMEN = [
    {"name": "Verkehr und Mobilität", "stichworte": [
        r"verkehr", r"\bvelo", r"\btram", r"\bbvb\b", r"parkpl", r"parkier", r"parking", r"strasse\b", r"strassen",
        r"\bauto", r"motorfahr", r"tempo", r"\böv\b", r"\bbus", r"mobilit", r"fussg", r"signalis", r"rheintunnel",
        r"autobahn", r"zubringer", r"taxi", r"scooter", r"anliefer", r"lieferverkehr", r"margarethen", r"herzstück",
        r"bahn", r"\bsbb\b", r"fahrspur", r"kreisel", r"lichtsignal", r"ladestation", r"e-mobil"]},
    {"name": "Wohnen, Bau und Stadtentwicklung", "stichworte": [r"geschossfläche", r"verdicht", r"vorstadt", r"quartier", r"eigentüm", r"grundeigen", r"öffentlichen raum", r"allmend", 
        r"wohn", r"\bmiet", r"mieter", r"bebauungsplan", r"zonen", r"\bareal", r"richtplan", r"stadtentwickl",
        r"denkmal", r"stadtbild", r"klybeck", r"dreispitz", r"hochhaus", r"freiraum", r"bauland", r"baubewillig",
        r"\bbau(en|t|vorhaben|projekt|gesetz)", r"neubau", r"umbau", r"sanierung", r"liegenschaft", r"boden",
        r"baurecht", r"wohnschutz", r"genossenschaft", r"eigenmietwert", r"\bplatz\b", r"rosental", r"hafenareal"]},
    {"name": "Finanzen und Steuern", "stichworte": [
        r"steuer", r"budget", r"finanz", r"gebühr", r"\babgabe", r"schulden", r"defizit", r"überschuss",
        r"kredit", r"pensionskasse", r"kantonalbank", r"\bbkb\b", r"ausgaben", r"sparen", r"spar", r"tarif",
        r"lastenausgleich", r"\bnfa\b", r"erbschaft", r"vermögen", r"oecd", r"mindeststeuer"]},
    {"name": "Wirtschaft, Gewerbe und Arbeit", "stichworte": [r"erwerbstätig", r"referenzalter", r"bewilligungsverfahren", r"\bbewilligung", r"gastgewerb", r"wirt", 
        r"wirtschaft", r"gewerbe", r"\bkmu", r"unternehm", r"detailhandel", r"gastro", r"restaurant", r"\bladen",
        r"läden", r"öffnungszeit", r"arbeitsmarkt", r"arbeitslos", r"mindestlohn", r"\blohn", r"löhne", r"messe",
        r"tourismus", r"wirtschaftsstandort", r"standortförder", r"life.?science", r"pharma", r"start.?up", r"innovation", r"bürokrat",
        r"regulier", r"fachkräft", r"lehrstell", r"berufsbild", r"beschaffung", r"submission", r"arbeitsbeding",
        r"innenstadt", r"\bmarkt", r"fonds.*betrieb", r"handwerk", r"arbeitnehm", r"arbeitgeb", r"sonntagsverkauf"]},
    {"name": "Bildung und Jugend", "stichworte": [r"grundkompetenz", r"unterricht", r"einführungsklass", r"lehrplan", r"matur", r"lehrkräft", r"\bbks\b", 
        r"schul", r"bildung", r"lehrperson", r"lehrer", r"universit", r"\buni\b", r"fhnw", r"\bkita", r"tagesbetreu",
        r"tagesstruktur", r"kinder", r"jugend", r"gymnas", r"ausbildung", r"stipendi", r"lernende", r"frühförder",
        r"\beth\b", r"forschung", r"hochschul", r"musikschul"]},
    {"name": "Gesundheit", "stichworte": [r"myopie", r"suizid", r"prävention", r"\bbgi\b", r"krankheit", r"psych", 
        r"gesundheit", r"spital", r"\busb\b", r"\bukbb\b", r"pflege", r"ärzt", r"arzt", r"medizin", r"psychiat",
        r"krankenkass", r"krankenvers", r"prämie", r"\bsucht", r"drogen", r"apothek", r"notfall", r"patient",
        r"impf", r"covid", r"corona", r"cannabis", r"hausarzt"]},
    {"name": "Soziales, Familie und Integration", "stichworte": [
        r"sozial", r"armut", r"ergänzungsleist", r"prämienverbill", r"familie", r"elternzeit", r"\balter",
        r"senior", r"asyl", r"migration", r"integration", r"flüchtl", r"behinder", r"gleichstell", r"frauen",
        r"lgbt", r"queer", r"diskrimin", r"rassis", r"obdach", r"existenz", r"betreuung", r"care", r"ausländ",
        r"einbürger", r"sans.?papiers", r"kinderbetreu", r"ahv", r"rente"]},
    {"name": "Sicherheit, Ordnung und Justiz", "stichworte": [
        r"polizei", r"sicherheit", r"kriminal", r"gewalt", r"justiz", r"gericht", r"staatsanwalt", r"strafvollzug",
        r"\bdemo", r"kundgebung", r"littering", r"(?<!tages)(?<!geschäfts)ordnung", r"feuerwehr", r"rettung", r"videoüberwach",
        r"überwachung", r"extremis", r"radikalis", r"terror", r"einbruch", r"vandal", r"sprayer", r"dreirosen",
        r"kleinbasel", r"messer", r"waffe", r"bettel", r"dealer", r"kontrolle"]},
    {"name": "Umwelt, Klima und Energie", "stichworte": [r"sprüh", r"kühl", r"schatten", r"brunnen", 
        r"klima", r"energie", r"umwelt", r"\bco2", r"solar", r"photovolt", r"fernwärme", r"\bgas", r"\bstrom",
        r"\biwb\b", r"lärm", r"abfall", r"recycl", r"\bwasser", r"biodivers", r"\bbaum", r"bäume", r"natur",
        r"hitze", r"netto.?null", r"emission", r"heizung", r"wärme", r"begrün", r"entsiegel", r"tier", r"lenkungsabgabe"]},
    {"name": "Kultur, Sport und Freizeit", "stichworte": [r"schwumm", r"swimm", r"\brhein\b", r"badi", r"\bbad\b", 
        r"kultur", r"museum", r"museen", r"theater", r"musik", r"kunst", r"fasnacht", r"\bsport", r"stadion",
        r"schwimm", r"gartenbad", r"freizeit", r"\bclub", r"nachtleben", r"bibliothek", r"\besc\b", r"eurovision",
        r"veranstalt", r"anlass", r"\bevent", r"festival", r"\bzoo\b", r"rheinschwimm", r"herbstmesse", r"art basel"]},
    {"name": "Staat, Verwaltung und Digitalisierung", "stichworte": [r"pensionier", r"tagesordnung", r"\bmotion\b", r"rechtlich", r"kantonsangestellt", r"behörde", r"staatsangestellt", r"chef", r"leiter", 
        r"verwaltung", r"digital", r"regierung", r"grosse[nr]? rat", r"parlament", r"\bwahl", r"abstimm",
        r"stimmrecht", r"verfassung", r"gemeinde", r"riehen", r"bettingen", r"staatspersonal", r"personal",
        r"datenschutz", r"transparenz", r"e-government", r"informatik", r"\bit\b", r"öffentlichkeitsprinzip",
        r"departement", r"amt\b", r"ämter", r"kommission", r"geschäftsordnung", r"ombuds", r"open data",
        r"künstliche intelligenz", r"\bki\b", r"\bcyber"]},
    {"name": "Region, Bund und Europa", "stichworte": [
        r"region", r"baselland", r"basel-landschaft", r"beider basel", r"trinational", r"grenz", r"\beu\b",
        r"europa", r"europä", r"elsass", r"frankreich", r"deutschland", r"partnerschaft", r"standesinitiative",
        r"\bbund\b", r"bundesrat", r"eidgen", r"interkantonal", r"euroairport", r"flughafen", r"rheinhäfen", r"hafen"]},
]

_COMPILED = [(t["name"], [re.compile(s) for s in t["stichworte"]]) for t in THEMEN]
# Füllwörter aus Titeln wie «Anzug Hans Muster und Konsorten betreffend ...» weglassen
_KOPF = re.compile(r"^.*?\b(betreffend|betr\.|zum|zur|zu den|über)\b", re.I)


def _treffer(text):
    s = text.lower()
    return {name: sum(1 for r in regs if r.search(s)) for name, regs in _COMPILED}


def thema_von(titel, thema_pd=None):
    titel = titel or ""
    kern = _KOPF.sub("", titel, count=1) if _KOPF.search(titel) else titel
    punkte = _treffer(kern)
    if thema_pd:
        for name, n in _treffer(thema_pd).items():
            punkte[name] += 3 * n
    best = max(punkte.values())
    if best == 0:
        return "Übriges"
    for name, _ in _COMPILED:
        if punkte[name] == best:
            return name
    return "Übriges"
