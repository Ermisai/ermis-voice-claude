"""Frases técnicas como o Claude responde, com o que o ouvinte deve entender (palavras que precisam aparecer na
transcrição de volta). Usadas no teste unitário e na ida e volta TTS -> STT (tests/ida_e_volta.py)."""

FRASES: list[tuple[str, list[str]]] = [
    ("A latência caiu para 140 ms no p50.", ["cento e quarenta", "milissegundos"]),
    ("Rodei 541 testes e 1 falhou.", ["quinhentos e quarenta e um", "falhou"]),
    ("A versão 0.5.2 corrige o eco.", ["zero ponto cinco ponto dois"]),
    ("O arquivo tem 2,5 MB e 3.200 linhas.", ["dois vírgula cinco", "megabytes", "três mil e duzentas"]),
    ("Isso usa 5% da CPU.", ["cinco por cento"]),
    ("Demorou ~1,5 s, contra 2-3 s antes.", ["cerca de um vírgula cinco segundos", "dois a três segundos"]),
    ("O build levou 12 min e gerou 2 falhas.", ["doze minutos", "duas falhas"]),
    ("Custa R$ 0,45 por minuto, ou US$ 5,81 no total.", ["quarenta e cinco centavos", "cinco dólares"]),
    ("A reunião é às 14:30 do dia 31/10/2026.", ["catorze e trinta", "trinta e um de outubro"]),
    ("O WER foi de 13,7% no CORAA.", ["treze vírgula sete por cento"]),
    ("Use Python 3.12 e Node 20.", ["três ponto doze", "vinte"]),
    ("O commit 6fa792b mudou o turn_check_ms.", ["hash", "turn check"]),
    ("Abra o PR #12 e rode com --force.", ["número doze", "force"]),
    ("O STT roda a 16 kHz com 8 GB de RAM.", ["dezesseis quilo-hertz", "oito gigabytes"]),
    ("Isso ficou 3x mais rápido, de 900 para 300 ms.", ["três vezes", "novecentos", "trezentos milissegundos"]),
    ("O useEffect roda 1 vez por render.", ["use effect", "uma vez"]),
    ("Faltam 10k tokens no contexto de 1M.", ["dez mil tokens", "um milhão"]),
    ("Se x >= 10, retorna -1.", ["maior ou igual a dez", "menos um"]),
    ("O 1º teste passou e a 2ª rodada também.", ["primeiro", "segunda"]),
    ("Tem 1.303 ligações e 22 sessões abertas.", ["mil trezentas e três", "vinte e duas"]),
]
