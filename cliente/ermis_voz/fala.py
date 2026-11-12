"""O texto como deve ser falado: a voz sintética lê palavras em português e não sabe ler dígitos nem símbolos.

Medido em 31/10/2026, sintetizando e transcrevendo de volta: "140 ms no p50" saiu "Raimundo",
"541 testes e 1 falhou" saiu "cinquenta mil testes e riso", "0.5.2" saiu "Sanvali", "2,5 MB" saiu "CIMIBI". Por isso
tudo o que o Claude responde passa por aqui antes do TTS, nesta ordem:

1. datas, horas, moeda, versões, faixas, porcentagem e números com unidade (ms, s, MB, kHz, %, x...);
2. números soltos por extenso, com o gênero do substantivo seguinte ("duas falhas", "um teste", "duzentas linhas"),
   decimais com vírgula, milhares, negativos, ordinais, zeros à esquerda e sequências longas dígito a dígito;
3. símbolos (~, >=, ->, &, #12, ±), abreviações (e.g., vs., etc.), identificadores de código (snake_case, camelCase,
   a.b, --flag) e hashes de commit;
4. siglas que sobrarem em maiúsculas soletradas ("STT" -> "ésse tê tê"), depois do léxico de pronúncia.
"""

from __future__ import annotations

import re

# ── números por extenso ─────────────────────────────────────────────────────
_UNIDADES = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
             "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
             "oitocentos", "novecentos"]
_GRANDES = [(10**12, "trilhão", "trilhões"), (10**9, "bilhão", "bilhões"), (10**6, "milhão", "milhões")]


def _feminino(palavras: str) -> str:
    out = re.sub(r"\bum\b", "uma", palavras)
    out = re.sub(r"\bdois\b", "duas", out)
    return re.sub(r"\b(duz|trez|quatroc|quinh|seisc|setec|oitoc|novec)entos\b", r"\1entas", out).replace(
        "quinhentas", "quinhentas"
    )


def _ate_mil(n: int) -> str:
    if n < 20:
        return _UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _DEZENAS[d] + (f" e {_UNIDADES[u]}" if u else "")
    if n == 100:
        return "cem"
    c, resto = divmod(n, 100)
    return _CENTENAS[c] + (f" e {_ate_mil(resto)}" if resto else "")


def por_extenso(n: int, feminino: bool = False) -> str:
    """Inteiro por extenso em pt-BR ("mil e duzentos", "dois milhões e quinhentos mil")."""
    if n < 0:
        return "menos " + por_extenso(-n, feminino)
    if n < 1000:
        txt = _ate_mil(n)
        return _feminino(txt) if feminino else txt
    partes: list[tuple[int, str]] = []  # (valor do grupo, texto)
    resto = n
    for valor, sing, plur in _GRANDES:
        if resto >= valor:
            q, resto = divmod(resto, valor)
            partes.append((q * valor, f"{_ate_mil(q) if q < 1000 else por_extenso(q)} {sing if q == 1 else plur}"))
    if resto >= 1000:
        q, resto = divmod(resto, 1000)
        txt = "mil" if q == 1 else f"{_ate_mil(q)} mil"
        partes.append((q * 1000, _feminino(txt) if feminino else txt))
    if resto:
        txt = _ate_mil(resto)
        partes.append((resto, _feminino(txt) if feminino else txt))
    out = partes[0][1]
    for i, (valor, txt) in enumerate(partes[1:], start=1):
        ultimo = i == len(partes) - 1
        # "mil e duzentos", "mil e cinco", mas "mil duzentos e cinquenta"
        junta = " e " if ultimo and (valor < 100 or valor % 100 == 0) else " "
        out += junta + txt
    return out


def digitos(s: str) -> str:
    return " ".join(_UNIDADES[int(c)] for c in s if c.isdigit())


def _fracao(s: str) -> str:
    """A parte depois da vírgula: "5" -> "cinco", "45" -> "quarenta e cinco", "05" e "125" dígito a dígito."""
    if len(s) <= 2 and not s.startswith("0"):
        return por_extenso(int(s))
    return digitos(s)


def decimal(inteiro: str, fracao: str, feminino: bool = False) -> str:
    return f"{por_extenso(int(inteiro), feminino)} vírgula {_fracao(fracao)}"


# ── gênero do substantivo que vem depois ────────────────────────────────────
_MASC_EM_A = {"problema", "sistema", "programa", "tema", "dia", "mapa", "esquema", "idioma", "clima", "diagrama",
              "telefonema", "planeta", "cometa", "dilema", "lema", "sofá", "poema", "fantasma", "pijama", "tchau"}
_FEM_OUTRAS = {"vez", "vezes", "hora", "horas", "imagem", "imagens", "mensagem", "mensagens", "ordem", "ordens",
               "chave", "chaves", "rede", "redes", "parte", "partes", "tarde", "noite", "fase", "fases", "classe",
               "classes", "base", "bases", "lib", "libs", "issue", "issues", "branch", "branches", "key", "keys",
               "query", "queries", "thread", "threads", "task", "tasks", "flag", "flags", "string", "strings",
               "tabela", "tabelas", "vCPU", "vCPUs", "CPU", "CPUs", "GPU", "GPUs", "API", "APIs", "URL", "URLs"}


# Palavras que vêm depois de um número sem ser o que ele conta ("de 900 para 300", "1 a cada 3")
_NAO_SUBSTANTIVO = {"a", "à", "as", "às", "o", "os", "e", "ou", "de", "da", "das", "do", "dos", "em", "na", "nas",
                    "no", "nos", "para", "pra", "por", "com", "sem", "sobre", "entre", "até", "cada", "contra",
                    "que", "se", "mais", "menos", "ainda", "agora", "já", "só", "também", "então", "ela", "ele",
                    "essa", "esta", "isso", "uma", "um", "outra", "toda", "nenhuma", "alguma", "vírgula", "ponto"}


def _e_feminino(palavra: str | None) -> bool:
    if not palavra:
        return False
    original = palavra.strip(".,;:!?()\"'")
    w = original.lower()
    if not w or w in _NAO_SUBSTANTIVO:
        return False
    if w in _FEM_OUTRAS or original in _FEM_OUTRAS:
        return True
    singular = w[:-1] if w.endswith("s") and len(w) > 3 else w
    if singular in _MASC_EM_A or w in _MASC_EM_A:
        return False
    return bool(re.search(r"(a|ção|são|gem|dade|ite)$", singular) or re.search(r"(ções|sões|gens|dades)$", w))


# ── unidades ────────────────────────────────────────────────────────────────
# símbolo -> (singular, plural, feminino)
_UNIDADES_MEDIDA: dict[str, tuple[str, str, bool]] = {
    "ms": ("milissegundo", "milissegundos", False),
    "µs": ("microssegundo", "microssegundos", False),
    "us": ("microssegundo", "microssegundos", False),
    "ns": ("nanossegundo", "nanossegundos", False),
    "s": ("segundo", "segundos", False),
    "seg": ("segundo", "segundos", False),
    "min": ("minuto", "minutos", False),
    "h": ("hora", "horas", True),
    "KB": ("quilobyte", "quilobytes", False), "kB": ("quilobyte", "quilobytes", False),
    "MB": ("megabyte", "megabytes", False), "GB": ("gigabyte", "gigabytes", False),
    "TB": ("terabyte", "terabytes", False), "KiB": ("quilobyte", "quilobytes", False),
    "MiB": ("megabyte", "megabytes", False), "GiB": ("gigabyte", "gigabytes", False),
    "B": ("byte", "bytes", False),
    "kbps": ("quilobit por segundo", "quilobits por segundo", False),
    "Mbps": ("megabit por segundo", "megabits por segundo", False),
    "Hz": ("hertz", "hertz", False), "kHz": ("quilo-hertz", "quilo-hertz", False),
    "MHz": ("mega-hertz", "mega-hertz", False), "GHz": ("giga-hertz", "giga-hertz", False),
    "dB": ("decibel", "decibéis", False),
    "px": ("pixel", "pixels", False),
    "ºC": ("grau", "graus", False), "°C": ("grau", "graus", False),
    "km": ("quilômetro", "quilômetros", False), "m": ("metro", "metros", False),
    "cm": ("centímetro", "centímetros", False), "mm": ("milímetro", "milímetros", False),
    "kg": ("quilo", "quilos", False), "g": ("grama", "gramas", False),
    "x": ("vez", "vezes", True),
    "k": ("mil", "mil", False), "K": ("mil", "mil", False),
    "M": ("milhão", "milhões", False),
    "tok": ("token", "tokens", False),
    "pp": ("ponto percentual", "pontos percentuais", False),
}
_UNIDADE_RE = "|".join(sorted((re.escape(u) for u in _UNIDADES_MEDIDA), key=len, reverse=True))

_NUM = r"\d+(?:[.,]\d+)*"
_MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]
_ORDINAIS_M = ["", "primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto", "sétimo", "oitavo", "nono",
               "décimo"]
_LETRAS = {"a": "á", "b": "bê", "c": "cê", "d": "dê", "e": "é", "f": "éfe", "g": "gê", "h": "agá", "i": "í",
           "j": "jota", "k": "cá", "l": "éle", "m": "ême", "n": "êne", "o": "ó", "p": "pê", "q": "quê", "r": "érre",
           "s": "ésse", "t": "tê", "u": "u", "v": "vê", "w": "dáblio", "x": "xis", "y": "ípsilon", "z": "zê"}
# Siglas que se falam como palavra (não soletrar)
_SIGLAS_PALAVRA = {"OK": "okei", "NASA": "nasa", "UNESCO": "unesco", "PIX": "pix", "CEP": "cep", "SUS": "sus",
                   "INSS": "í ene ésse ésse", "LGPD": "éle gê pê dê", "ASCII": "asqui", "GIF": "guif", "RAM": "ram",
                   "ROM": "rom", "LAN": "lan", "WAV": "uêiv", "SIM": "sim", "NAO": "não", "FAQ": "éfe a quê"}


def _numero(texto: str, feminino: bool = False) -> str:
    """Um número como está escrito: milhares com ponto (pt) ou vírgula (en), decimal com vírgula (pt) ou ponto."""
    s = texto
    neg = s.startswith("-")
    s = s.lstrip("-")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s) and not s.startswith("0."):
        out = por_extenso(int(s.replace(".", "")), feminino)
    elif re.fullmatch(r"\d{1,3}(,\d{3}){2,}", s):
        out = por_extenso(int(s.replace(",", "")), feminino)
    elif m := re.fullmatch(r"(\d+)[.,](\d+)", s):
        out = decimal(m.group(1), m.group(2), feminino)
    elif s.isdigit():
        if len(s) > 1 and s.startswith("0"):
            out = digitos(s)
        elif len(s) > 12:
            out = digitos(s)
        else:
            out = por_extenso(int(s), feminino)
    else:
        out = digitos(s)
    return ("menos " + out) if neg else out


def _plural(texto_num: str) -> bool:
    s = texto_num.lstrip("-")
    return not re.fullmatch(r"0*1", s)  # "1 ms" singular; "1,5 s" plural (pt-BR fala "um vírgula cinco segundos")


def _sub_unidade(m: re.Match) -> str:
    num, unidade, resto = m.group("num"), m.group("un"), m.group("resto") or ""
    sing, plur, fem = _UNIDADES_MEDIDA[unidade]
    if unidade in ("k", "K", "M"):  # 10k tokens: "dez mil tokens"; 1M: "um milhão"
        valor = _numero(num)
        if unidade in ("k", "K"):
            return f"{valor} mil{resto}"
        return f"{valor} {'milhão' if not _plural(num) else 'milhões'}{resto}"
    nome = plur if _plural(num) else sing
    return f"{_numero(num, fem)} {nome}{resto}"


def _hora(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return m.group(0)
    if mi == 0:
        return f"{por_extenso(h, True)} {'hora' if h == 1 else 'horas'}"
    return f"{por_extenso(h, True)} e {por_extenso(mi)}"


def _data(m: re.Match) -> str:
    d, mes = int(m.group(1)), int(m.group(2))
    ano = m.group(3)
    if not (1 <= d <= 31 and 1 <= mes <= 12):
        return m.group(0)
    dia = "primeiro" if d == 1 else por_extenso(d)
    out = f"{dia} de {_MESES[mes]}"
    if ano:
        a = int(ano) + (2000 if len(ano) == 2 else 0)
        out += f" de {por_extenso(a)}"
    return out


def _data_sem_ano(m: re.Match) -> str:
    d, mes = int(m.group(2)), int(m.group(3))
    if not (1 <= d <= 31 and 1 <= mes <= 12):
        return f"{m.group(2)}/{m.group(3)}"
    return f"{'primeiro' if d == 1 else por_extenso(d)} de {_MESES[mes]}"


_DENOMINADORES = {2: ("meio", "meios"), 3: ("terço", "terços"), 4: ("quarto", "quartos"), 5: ("quinto", "quintos"),
                  6: ("sexto", "sextos"), 7: ("sétimo", "sétimos"), 8: ("oitavo", "oitavos"), 9: ("nono", "nonos"),
                  10: ("décimo", "décimos"), 100: ("centésimo", "centésimos"), 1000: ("milésimo", "milésimos")}


def _fracao_barra(m: re.Match) -> str:
    """'2/3' -> 'dois terços', '1/2' -> 'metade', '3/7' -> 'três de sete' (n de d: "3/5 testes passaram")."""
    n, d = int(m.group(1)), int(m.group(2))
    if d == 0:
        return m.group(0)
    # "dois terços DAS falas" soa como fração; "3/5 testes passaram" é "três de cinco testes"
    partitivo = re.match(r"\s+(?:d[oa]s?|de)\b", m.string[m.end():]) is not None
    if n == 1 and d == 2 and partitivo:
        return "metade"
    if partitivo and n < d and d in _DENOMINADORES:
        sing, plur = _DENOMINADORES[d]
        return f"{por_extenso(n)} {sing if n == 1 else plur}"
    return f"{por_extenso(n)} de {por_extenso(d)}"


def _letra_numero(m: re.Match) -> str:
    """'B0' -> 'bê zero', 'H264' -> 'agá dois seis quatro', 'F1' -> 'éfe um'."""
    letra, num = m.group(1), m.group(2)
    nome = _LETRAS.get(letra.lower(), letra)
    falado = digitos(num) if len(num) > 2 or num.startswith("0") and len(num) > 1 else por_extenso(int(num))
    return f"{nome} {falado}"


def _moeda(m: re.Match) -> str:
    simbolo, valor = m.group(1), m.group(2)
    nome = {"R$": ("real", "reais"), "US$": ("dólar", "dólares"), "$": ("dólar", "dólares"),
            "€": ("euro", "euros")}[simbolo]
    v = valor.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", valor) else valor
    if "," in v:
        inteiro, cent = v.split(",", 1)
    elif re.fullmatch(r"\d+\.\d{2}", v):
        inteiro, cent = v.split(".", 1)
    else:
        inteiro, cent = v.replace(",", ""), ""
    i = int(inteiro or 0)
    c = int((cent + "0")[:2]) if cent else 0
    partes = []
    if i or not c:
        partes.append(f"{por_extenso(i)} {nome[0] if i == 1 else nome[1]}")
    if c:
        partes.append(f"{por_extenso(c)} {'centavo' if c == 1 else 'centavos'}")
    return " e ".join(partes)


def _versao(m: re.Match) -> str:
    partes = m.group("v").split(".")
    return " ponto ".join(_numero(p) for p in partes)


def _ordinal(m: re.Match) -> str:
    n, marca = int(m.group(1)), m.group(2)
    if 1 <= n <= 10:
        txt = _ORDINAIS_M[n]
        return txt[:-1] + "a" if marca in ("ª", "a") else txt
    return f"número {por_extenso(n)}"


def _numero_solto(m: re.Match) -> str:
    num = m.group(0)
    depois = m.string[m.end():]
    prox = re.match(r"\s*([A-Za-zÀ-ú]+)", depois)
    return _numero(num, _e_feminino(prox.group(1) if prox else None))


def _faixa(m: re.Match) -> str:
    a, b = m.group(1), m.group(2)
    depois = m.string[m.end():]
    prox = re.match(r"\s*([A-Za-zÀ-ú]+)", depois)
    fem = _e_feminino(prox.group(1) if prox else None)
    return f"{_numero(a, fem)} a {_numero(b, fem)}"


def _sigla(m: re.Match) -> str:
    w = m.group(0)
    base, plural = (w[:-1], True) if w.endswith("s") and w[:-1].isupper() else (w, False)
    if base in _SIGLAS_PALAVRA:
        return _SIGLAS_PALAVRA[base] + ("s" if plural else "")
    letras = " ".join(_LETRAS.get(c.lower(), c) for c in base if c.isalpha())
    return letras + ("s" if plural else "")


def _camel(m: re.Match) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(0))


_ABREVIACOES = [
    (r"\be\.g\.", "por exemplo"), (r"\bi\.e\.", "isto é"), (r"\betc\.", "etcétera"), (r"\bex\.:", "por exemplo:"),
    (r"\bvs\.?(?=\s)", "versus"), (r"\baprox\.", "aproximadamente"), (r"\bnº\s*", "número "),
    (r"\bn\.º\s*", "número "), (r"\bp\.\s*ex\.", "por exemplo"), (r"\bobs\.:", "observação:"),
]
_SIMBOLOS = [
    (r"\s*(?:>=|≥)\s*", " maior ou igual a "), (r"\s*(?:<=|≤)\s*", " menor ou igual a "),
    (r"\s*(?:->|→|=>|⇒)\s*", " para "), (r"\s*(?:<-|←)\s*", " de "),
    (r"\s*±\s*", " mais ou menos "), (r"\s+&\s+", " e "), (r"\s*≈\s*", " cerca de "),
    (r"(?<!\w)~\s*(?=\d)", "cerca de "), (r"\s*×\s*", " vezes "),
    (r"(?<=\d)\s*\+\s*(?=\d)", " mais "), (r"(?<=\d)\s*=\s*(?=\d)", " igual a "),
    (r"(?<=\s)>(?=\s)", "maior que"), (r"(?<=\s)<(?=\s)", "menor que"), (r"(?<=\s)=(?=\s)", "igual a"),
    (r"\s*…\s*", ", "), (r"\s*\.\.\.\s*", ", "),
]


def normalizar(texto: str) -> str:
    t = texto
    for pat, rep in _ABREVIACOES:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    t = re.sub(r"(?<!\w)~\s*(?=\d)", "cerca de ", t)  # antes de o número virar palavra
    # hashes de commit e ids longos em hexadecimal: não dá para ler, e soletrar cansa
    t = re.sub(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", "hash", t)
    # moeda antes dos números
    t = re.sub(r"(R\$|US\$|€|\$)\s?(\d[\d.,]*\d|\d)", _moeda, t)
    # datas (antes da barra virar "barra") e horas. Sem o ano, só é data depois de "dia/em/até/desde/de" ou com o
    # mês por perto; o resto é fração: 04/11, "2/3 das falas" tinha virado "dois de março das falas"
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", _data, t)
    t = re.sub(r"(?i)\b((?:dia|dias|em|até|desde|de|entre|para|no dia)\s+)(\d{1,2})/(\d{1,2})\b(?!/)",
               lambda m: m.group(1) + _data_sem_ano(m), t)
    t = re.sub(r"(?<![\w/.])(\d{1,3})/(\d{1,4})(?![\w/])", _fracao_barra, t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b(?!:)", _hora, t)
    # versões: 0.5.2, v1.2, Python 3.12
    t = re.sub(r"(?<![\w.])v(?P<v>\d+(?:\.\d+)+)\b", lambda m: "versão " + _versao(m), t)
    t = re.sub(r"(?<![\w.,])(?P<v>\d+\.\d+\.\d+(?:\.\d+)*)(?![\w.])", _versao, t)
    t = re.sub(r"(?i)\b(?P<w>versão|version|python|node|java|go|rust|ruby|php|ubuntu|macos|ios|android|"
               r"opus|sonnet|haiku|claude|gpt|motor|engine|release)\s(?P<v>\d+\.\d+)\b",
               lambda m: f"{m.group('w')} {_versao(m)}", t)
    # percentis (p50, p90)
    t = re.sub(r"\bp(\d{2,3})\b", lambda m: "pê " + por_extenso(int(m.group(1))), t)
    # porcentagem e faixas com porcentagem
    t = re.sub(rf"(-?{_NUM})\s?[–-]\s?(-?{_NUM})\s?%", lambda m: f"{_numero(m.group(1))} a {_numero(m.group(2))} por cento", t)
    t = re.sub(rf"(-?{_NUM})\s?%", lambda m: f"{_numero(m.group(1))} por cento", t)
    # faixa com unidade: "100-700 ms" -> "cem a setecentos milissegundos"
    t = re.sub(rf"(?<![\w.,])({_NUM})\s?[–-]\s?({_NUM})\s?(?=(?:{_UNIDADE_RE})\b)", lambda m: f"{m.group(1)}~a~{m.group(2)} ", t)
    # número com unidade (o "~a~" de cima vira a faixa)
    def _faixa_unidade(m: re.Match) -> str:
        a, b, un = m.group(1), m.group(2), m.group("un")
        sing, plur, fem = _UNIDADES_MEDIDA[un]
        return f"{_numero(a, fem)} a {_numero(b, fem)} {plur}"
    t = re.sub(rf"({_NUM})~a~({_NUM})\s(?P<un>{_UNIDADE_RE})\b", _faixa_unidade, t)
    t = re.sub(rf"(?<![\w.,])(?P<num>-?{_NUM})\s?(?P<un>{_UNIDADE_RE})(?P<resto>\b|(?=\s|$|[.,;:!?)]))", _sub_unidade, t)
    # ordinais 1º, 2ª
    t = re.sub(r"\b(\d+)\s?([ºª°]|(?<=\d)o\b|(?<=\d)a\b)", _ordinal, t)
    # #12 -> número doze
    t = re.sub(r"#(\d+)", lambda m: "número " + _numero(m.group(1)), t)
    # faixas soltas: "3-5 testes"
    t = re.sub(rf"(?<![\w.,])({_NUM})\s?[–-]\s?({_NUM})(?![\w.,])", _faixa, t)
    # negativos
    t = re.sub(rf"(?<![\w.,-])-({_NUM})", lambda m: "menos " + _numero(m.group(1)), t)
    # símbolos
    for pat, rep in _SIMBOLOS:
        t = re.sub(pat, rep, t)
    # uma letra maiúscula e um número ("B0", "F1", "H264"): a letra pelo nome (sozinho o TTS não a lê)
    t = re.sub(r"\b([A-Z])(\d{1,4})\b", _letra_numero, t)
    # números grudados em letras (test_v052, h264, x86): separa e lê dígito a dígito quando têm zero à esquerda
    t = re.sub(r"(?<=[A-Za-z_])(\d+)", lambda m: " " + _numero(m.group(1)), t)
    t = re.sub(r"(\d+)(?=[A-Za-z])", lambda m: _numero(m.group(1)) + " ", t)
    # números soltos
    t = re.sub(rf"(?<![\w]){_NUM}(?![\w])", _numero_solto, t)
    # código: --flag, snake_case, camelCase, a.b
    t = re.sub(r"(?<!\w)--?(?=[a-zA-Z])", "", t)
    t = re.sub(r"(?<=\w)_(?=\w)", " ", t)
    t = re.sub(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b", _camel, t)
    t = re.sub(r"(?<=[a-z])\.(?=[a-z])", " ponto ", t)
    return " ".join(t.split())


def soletrar_siglas(texto: str) -> str:
    """Siglas que sobraram em maiúsculas (depois do léxico): "STT" -> "ésse tê tê", "OK" -> "okei"."""
    return re.sub(r"\b[A-Z]{2,6}s?\b", _sigla, texto)
