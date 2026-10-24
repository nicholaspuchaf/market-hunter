"""Conservative rules: uncertain seniority and eligibility remain visible for review."""

import html
import re
import unicodedata
from html.parser import HTMLParser


def normalized(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "li", "h1", "h2", "h3", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(content: str) -> str:
    parser = TextExtractor()
    parser.feed(html.unescape(content))
    return re.sub(r"\n[ \t]*\n+", "\n\n", "".join(parser.parts)).strip()


AREAS = {
    "Desenvolvimento": r"\b(developer|desenvolvedor\w*|desenvolvimento (?:de )?(?:software|sistemas|aplicac\w*)|software|backend|back.end|frontend|front.end|full.?stack|programador\w*|mobile|android|ios|analista de sistemas|arquiteta?\w* de solucoes|enterprise architect|quality assurance|qa|test engineer|engenh\w* de testes|tech\s*lead)\b",
    "DevOps": r"\b(devops|sre|site reliability|platform engineer\w*|engenh\w* de plataforma)\b",
    "Infraestrutura": r"\b(infraestrutura|infrastructure|cloud|redes|networks?|sysadmin|administrador\w* de sistemas|plataforma de dados|dbre|dba|banco de dados|database|platform engineering|engenharia de plataformas?)\b",
    "IA": r"\b(inteligencia artificial|artificial intelligence|machine learning|ml engineer|ai engineer\w*|ia|llm|deep learning|mlops|cientista de dados|data scientist|ai\s*&\s*automation)\b",
    "Dados": r"\b(data engineer\w*|engenh\w* de dados|analytics engineer\w*|data analyst|analista de dados|big data)\b",
    "Segurança": r"\b(cybersecurity|cyber security|security engineer\w*|seguranca (?:da informacao|cibernetica)|appsec|devsecops|soc analyst)\b",
    "Suporte de TI": r"\b(suporte (?:de |em |a )?(?:ti|tecnico|sistemas)|help.?desk|service.?desk|it support)\b",
}


SENIORITY_PATTERNS = {
    "Estágio": r"\b(estagio|estagiari\w*|intern|internship|aprendiz)\b",
    "Júnior": r"\b(junior|jr|entry.?level|associate)\b",
    "Pleno": r"\b(plen[oa]|pl|mid.?level|mid|intermediate)\b",
    "Sênior": r"\b(senior|sr|staff|principal)\b",
    "Tech Lead": r"\b(tech\s*lead|technical lead|lider(?:anca)? tecnic[oa]|lead (?:software|backend|frontend|engineer)|engineering lead)\b",
    "Especialista": r"\b(especialista|specialist)\b",
    "Liderança": r"\b(gerente|head|coordenador\w*|engineering manager)\b",
}


def classify(title: str, location: str, description: str, departments: str = "") -> dict:
    title_text = normalized(title)
    # Job title and department carry stronger intent than boilerplate in the description.
    area_text = normalized(f"{title} {departments}")
    categories = [name for name, pattern in AREAS.items() if re.search(pattern, area_text)]
    if not categories and re.search(
        r"\b(tecnologia|technology|tech|ti|information technology|engineering|engenharia de software|arquiteta?\w*|sistemas e produtos)\b",
        area_text,
    ):
        # A technology department can identify a role whose title is otherwise generic.
        categories = ["Tecnologia"]
    seniority_tags = [
        name for name, pattern in SENIORITY_PATTERNS.items() if re.search(pattern, title_text)
    ]
    # Do not assume a specialist or manager is explicitly advertised as senior.
    seniority = " / ".join(seniority_tags) if seniority_tags else "Não informada"

    place = normalized(location)
    mode_text = normalized(f"{title} {location}")
    if re.search(r"\b(hibrid\w*|hybrid)\b", mode_text):
        mode = "Híbrido"
    elif re.search(r"\b(remot\w*|anywhere|worldwide)\b", mode_text):
        mode = "Remoto"
    elif re.search(r"\b(presencial|on.?site)\b", mode_text):
        mode = "Presencial"
    else:
        mode = "Não informado"

    # A state label alone does not prove the office is in São Paulo city.
    local = bool(re.search(r"\bcampinas\b|\bsao paulo\s*(?:,|/|-)\s*(?:sao paulo|sp)\b", place))
    local = local or place.strip() in {"sao paulo", "sao paulo, brazil", "sao paulo, brasil"}
    fit = "Revisar"
    if local and mode in {"Presencial", "Híbrido"}:
        fit = "Compatível"
    elif mode == "Remoto":
        if re.search(
            r"\b(brasil|brazil|worldwide|anywhere|global|latam|latin america|america latina)\b",
            place,
        ):
            fit = "Compatível"
    elif mode in {"Presencial", "Híbrido"} and place.strip() and not local:
        fit = "Fora do perfil"
    return {
        "categories": categories,
        "seniority": seniority,
        "seniority_tags": seniority_tags,
        "work_mode": mode,
        "location_fit": fit,
    }
