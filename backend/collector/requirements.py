"""Extract explicit technology mentions and targeted openings, without inferring people."""

import re

from collector.classify import normalized

LANGUAGES = {
    "Python": r"\bpython\b",
    "Java": r"\bjava\b",
    "JavaScript": r"\b(java\s*script|javascript|node\.?js)\b",
    "TypeScript": r"\btypescript\b",
    "Kotlin": r"\bkotlin\b",
    "Go": r"\b(golang|go language|linguagem go)\b|(?<!\w)Go(?!\w)",
    "C#": r"(?<!\w)c\s*#|\bcsharp\b",
    "C++": r"(?<!\w)c\s*\+\+",
    "C": r"\blinguagem c\b|\bc programming\b",
    "PHP": r"\bphp\b",
    "Ruby": r"\bruby\b",
    "Rust": r"\brust\b",
    "Swift": r"\bswift\b",
    "Dart": r"\bdart\b",
    "Scala": r"\bscala\b",
    "R": r"\blinguagem r\b|\br programming\b",
    "SQL": r"\bsql\b",
    "Shell/Bash": r"\b(bash|shell scripting|shell script)\b",
    "PowerShell": r"\bpowershell\b",
}

PLATFORMS = {
    "AWS": r"\b(aws|amazon web services)\b",
    "Azure": r"\bazure\b",
    "GCP": r"\b(gcp|google cloud(?: platform)?)\b",
    "Linux": r"\b(linux|ubuntu|debian|red hat|rhel|centos)\b",
}

TOOLS = {
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\b(kubernetes|k8s)\b",
    "Terraform": r"\bterraform\b",
    "Ansible": r"\bansible\b",
    "Git": r"\b(git|github|gitlab)\b",
    "CI/CD": r"\bci\s*/\s*cd\b|\b(integracao continua|continuous integration|continuous delivery)\b",
    "React": r"\breact(?:\.?js)?\b",
    "Angular": r"\bangular\b",
    "Vue": r"\bvue(?:\.?js)?\b",
    "Svelte": r"\bsvelte\b",
    "Node.js": r"\bnode\.?js\b",
    "Spring": r"\bspring(?: boot)?\b",
    ".NET": r"(?<!\w)\.net\b|\bdotnet\b",
    "PostgreSQL": r"\b(postgresql|postgres)\b",
    "MySQL": r"\bmysql\b",
    "MongoDB": r"\bmongodb\b",
    "Redis": r"\bredis\b",
    "Kafka": r"\bkafka\b",
    "RabbitMQ": r"\brabbitmq\b",
    "Spark": r"\b(?:apache )?spark\b",
    "PyTorch": r"\bpytorch\b",
    "TensorFlow": r"\btensorflow\b",
    "LLMs": r"\b(llms?|large language models?)\b",
    "Inglês": r"\b(ingles|english)\b",
}


def extract_requirements(title: str, description: str) -> dict:
    # Trim common company/benefits sections so boilerplate does not become a requirement.
    sections = []
    ignore = False
    for line in description.splitlines():
        heading = normalized(line.strip())
        if len(heading) < 120 and re.search(
            r"^(?:nossos beneficios|beneficios|benefits|sobre (?:nos|a empresa)|about us|diversidade|diversity|nosso compromisso|voce tem fome de que)",
            heading,
        ):
            ignore = True
        if len(heading) < 120 and re.search(
            r"^(?:requisitos|requirements|qualifications|qualificacoes|responsabilidades|responsibilities|o que (?:buscamos|esperamos|voce precisa)|diferenciais|nice to have|sua missao)",
            heading,
        ):
            ignore = False
        if not ignore:
            sections.append(line)
    content = f"{title}\n" + "\n".join(sections)
    text = normalized(content)

    def matches(patterns):
        result = []
        for name, pattern in patterns.items():
            # Go's capitalization distinguishes the language from ordinary English 'go'.
            if name == "Go":
                found = re.search(r"\b(golang|linguagem go|go language)\b", text) or re.search(
                    r"(?<!\w)Go(?!\w)", content
                )
            else:
                found = re.search(pattern, text)
            if found:
                result.append(name)
        return result

    languages = matches(LANGUAGES)
    platforms = matches(PLATFORMS)
    tools = matches(TOOLS)
    return {"language_tags": languages, "platform_tags": platforms, "requirement_tags": tools}


GROUPS = {
    "Mulheres": r"\b(mulheres|mulher|women|woman|female)\b",
    "Pessoas negras": r"\b(pessoas negras|pessoa negra|pessoas pretas|pessoas pardas|pretos e pardos|negr[oa]s?|black (?:people|professionals|candidates))\b",
    "PcD": r"\b(pcds?|pessoas? com deficiencia|profissionais com deficiencia|people with disabilities|person with a disability)\b",
}
TARGETING = (
    r"\b(?:exclusiv\w*|afirmativ\w*|destinad\w*|reservad\w*|apenas|somente|only|restricted)\b"
)


def affirmative_tags(title: str, description: str) -> list[str]:
    title_text = normalized(title)
    result = set()
    # Common explicit title markers, e.g. 'Backend (PcD)' or 'Vaga para mulheres'.
    for group, pattern in GROUPS.items():
        if re.search(rf"(?:\(|\[)\s*(?:{pattern})\s*(?:\)|\])", title_text):
            result.add(group)
        if re.search(rf"\bvaga\s+para\s+(?:{pattern})", title_text):
            result.add(group)
    for clause in re.split(r"[\n.!?;]", normalized(f"{title}\n{description}")):
        if re.search(
            r"\b(nao (?:(?:e|sao) )?(?:uma? )?(?:(?:vaga|oportunidade) )?(?:exclusiv|afirmativ)|nao se restringe|not exclusive)",
            clause,
        ):
            continue
        if (
            clause.strip() != title_text.strip()
            and not re.search(
                r"\b(vaga|oportunidade|posicao|candidatura|processo seletivo|opening|role|position|vacancy)\b",
                clause,
            )
            and not re.match(
                r"\s*(?:esta |essa )?(?:vaga )?(?:exclusiv\w*|afirmativ\w*|apenas|somente)\b",
                clause,
            )
        ):
            continue
        for anchor in re.finditer(TARGETING, clause):
            # Match only the target after the marker, rather than unrelated groups elsewhere.
            target = clause[anchor.end() : anchor.end() + 140]
            target = re.split(
                r"\b(mas|valorizamos|respeitamos|independente|independentemente|acolhemos)\b",
                target,
            )[0]
            for group, pattern in GROUPS.items():
                if re.search(pattern, target):
                    result.add(group)
    return [group for group in GROUPS if group in result]
