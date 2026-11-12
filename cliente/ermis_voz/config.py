"""Configuração do cliente: ~/.ermis-voz/config.json, com variáveis de ambiente por cima."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ermis_voz.chave import variantes

HOME = Path(os.environ.get("ERMIS_VOZ_HOME", "~/.ermis-voz")).expanduser()
CONFIG_PATH = HOME / "config.json"
SOCKET_PATH = HOME / "daemon.sock"
MODO_PATH = HOME / "modo"  # ferramenta | maos_livres | comando | leitura | desligado
APRENDIDOS_PATH = HOME / "aprendidos.json"
LOG_PATH = HOME / "daemon.log"
ESTADO_PATH = HOME / "estado.json"  # lido pelo painel (plugin ermis-voz-painel)
ATIVA_PATH = HOME / "ativa.json"  # escrito pelo painel da janela em uso: {sessao, t, cwd}
ATIVA_MS = 6000  # sem renovação por este tempo, nenhuma janela está em uso (não há quem veja a transcrição ao vivo)

# Frases de espera enquanto o Claude prepara a resposta (as do motor de ligação, sem "Ok": o TTS fala mal)
FRASES_PREENCHIMENTO = ["Hum, deixa eu ver.", "Certo, um momento.", "Entendi, só um instante.", "Tá, deixa eu olhar isso."]
FRASES_PACIENCIA = ["Ainda tô vendo aqui, só um instante.", "Tô trabalhando nisso, já te falo.",
                    "Só mais um pouquinho, tô quase lá."]


API_PADRAO = "https://voice-api.live.ermis.ai"  # a Ermis Voice API (a chave de cada pessoa, criada em app.ermis.ai)


@dataclass
class Config:
    servidor: str = API_PADRAO  # o endereço da Voice API
    token: str = ""  # a sua chave de API da Ermis (app.ermis.ai, Tokens API)
    paciencia: str = "normal"  # rapida | normal | longa
    voz: str = ""  # vazio: a padrão da conta (`ermis-voz vozes` lista as outras)
    velocidade: float = 1.0  # da fala, de 0.75 (mais devagar) a 1.25 (mais rápido), sem mudar o tom
    aec: str = "webrtc"  # webrtc | nenhum
    entrada: str = ""  # nome do microfone (vazio: o padrão)
    saida: str = ""  # nome do alto-falante (vazio: o padrão)
    barge_in: bool = True
    escuta_s: int = 120  # quanto o "conversar" espera a resposta
    # Frase de espera quando o Claude demora a responder depois de uma fala sua (desligue com false)
    preenchimento: bool = True
    preenchimento_ms: int = 900  # silêncio do Claude até a frase de espera
    paciencia_ms: int = 12000  # e até a frase de paciência (0: nenhuma)
    frases_preenchimento: list[str] = field(default_factory=lambda: list(FRASES_PREENCHIMENTO))
    frases_paciencia: list[str] = field(default_factory=lambda: list(FRASES_PACIENCIA))
    # Modo comando: só o que começa com a palavra-chave vira pedido ("Ermis, roda os testes"); `ermis-voz palavra X`
    palavra_chave: str = "Ermis"
    grafias_extras: list[str] = field(default_factory=list)  # como o STT escreve a sua palavra, se errar sempre
    janela_comando_s: float = 8.0  # depois de "Ermis." sozinho, a próxima fala vale como comando
    # Narração do que o Claude pensa e faz enquanto trabalha (o thinking e o texto antes de uma ferramenta),
    # resumida à primeira frase, no máximo uma a cada `pensamento_intervalo_s`; a resposta de verdade corta
    falar_pensamento: bool = True
    falar_progresso: bool = True
    pensamento_na_leitura: bool = True  # no modo leitura também ("vou rodar os testes…"); false: só as respostas
    pensamento_intervalo_s: float = 5.0
    pensamento_max_chars: int = 160
    # Leitura das respostas (modos leitura e comando): inteira até `leitura_inteiro_ate_s`; acima, um resumo de
    # ~`leitura_resumo_s` (a abertura que o próprio Claude escreve, ou o Haiku, ou extrativo); nunca mais que o teto
    leitura_inteiro_ate_s: float = 45.0
    leitura_resumo_s: float = 60.0
    leitura_max_s: float = 120.0
    # Várias janelas do Claude falando ao mesmo tempo: uma fala por vez; espera a vez no máximo `fila_max` falas (a
    # mais nova de cada sessão; quando enche, sai a mais antiga)
    fila_max: int = 3
    # A sessão da Voice API é cobrada por segundo: no modo ferramenta (ou desligado), sem uso por `ocioso_s`, o daemon
    # encerra; a próxima chamada de voz abre outra (0: nunca encerra)
    ocioso_s: int = 300

    def variantes(self) -> list[str]:
        """As grafias aceitas da palavra-chave (a principal primeiro)."""
        return variantes(self.palavra_chave or "Ermis", self.grafias_extras)

    @classmethod
    def load(cls) -> Config:
        data = {}
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})
        if cfg.servidor.startswith(("ws://", "wss://")):
            cfg.servidor = API_PADRAO  # o servidor próprio (até a 0.4.x) foi descontinuado: a voz é a Voice API
        for f in fields(cls):
            env = os.environ.get(f"VOZ_{f.name.upper()}")
            if env is not None:
                setattr(cfg, f.name, _cast(env, f.type))
        return cfg

    def save(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        CONFIG_PATH.chmod(0o600)  # tem o token


def _cast(value: str, typ):
    if str(typ).startswith("list"):
        return [v.strip() for v in value.split("|") if v.strip()]
    if typ in (bool, "bool"):
        return value.lower() in ("1", "true", "sim", "yes")
    if typ in (int, "int"):
        return int(value)
    if typ in (float, "float"):
        return float(value)
    return value


def modo() -> str:
    try:
        return MODO_PATH.read_text(encoding="utf-8").strip() or "ferramenta"
    except OSError:
        return "ferramenta"


def set_modo(valor: str) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    MODO_PATH.write_text(valor, encoding="utf-8")


def aprendidos() -> dict[str, str]:
    try:
        data = json.loads(APRENDIDOS_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_aprendido(ouvido: str, entendido: str) -> None:
    data = aprendidos()
    data[ouvido] = entendido
    HOME.mkdir(parents=True, exist_ok=True)
    APRENDIDOS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
