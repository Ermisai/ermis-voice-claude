"""O canal com a Voice API: áudio, tradução de eventos e erros (sem rede)."""

import json

import numpy as np
import pytest

from ermis_voz.voice_api import QUADRO, ErroApi, Para8k, VoiceApi, erro_http, mulaw


class Ws:
    def __init__(self) -> None:
        self.enviadas: list = []

    async def send(self, data) -> None:
        self.enviadas.append(data if isinstance(data, bytes) else json.loads(data))

    def json(self) -> list[dict]:
        return [m for m in self.enviadas if isinstance(m, dict)]


@pytest.fixture
def canal():
    c = VoiceApi("https://voice-api.example", "chave", termos=["pytest", "daemon.py"])
    c.ws = Ws()
    return c


def test_mulaw_silencio_e_extremos():
    assert mulaw(np.zeros(4, dtype=np.int16)) == b"\xff" * 4
    alto = mulaw(np.array([32767, -32768], dtype=np.int16))
    assert alto[0] == 0x80 and alto[1] == 0x00


def test_para8k_reduz_pela_metade():
    p = Para8k()
    tom = (np.sin(2 * np.pi * 440 * np.arange(1600) / 16000) * 10000).astype("<i2").tobytes()
    out = np.concatenate([p(tom[:640]), p(tom[640:])])
    assert out.size == 800
    assert 5000 < np.abs(out[100:]).max() < 11000  # 440 Hz passa sem perda


async def test_microfone_vai_em_quadros_de_20_ms(canal):
    await canal.enviar_audio(b"\x00\x00" * 480)  # 30 ms a 16 kHz
    quadros = [m for m in canal.ws.enviadas if isinstance(m, bytes)]
    assert [len(q) for q in quadros] == [QUADRO]  # 20 ms; os 10 ms que sobram esperam o próximo bloco


async def test_falar_prepara_o_texto_e_interrompe_so_quando_pedido(canal):
    await canal.enviar({"type": "falar", "id": "a", "texto": "Rodei o `pytest`: 3 testes passaram.",
                        "interromper": True})
    speak = canal.ws.json()[-1]
    assert speak["type"] == "speak" and speak["id"] == "a"
    assert "`" not in speak["text"] and "três" in speak["text"]
    assert not any(m["type"] == "interrupt" for m in canal.ws.json())  # nada tocava
    await canal.enviar({"type": "falar", "id": "b", "texto": "Outra.", "interromper": True})
    assert [m["type"] for m in canal.ws.json()] == ["speak", "interrupt", "speak"]
    assert (await canal._locais.get()) == {"type": "audio_cortado", "id": "a"}


async def test_barge_in_corta_a_fala_e_as_que_vinham_depois(canal):
    for fid in ("p1", "p2", "p3"):
        await canal.enviar({"type": "falar", "id": fid, "texto": f"Parte {fid}.", "interromper": False})
    await canal._traduzir({"type": "speak.started", "id": "p1"})
    assert await canal._traduzir({"type": "clear"}) == [{"type": "limpar"}]
    eventos = await canal._traduzir({"type": "barge_in", "id": "p1"})
    assert eventos[0]["type"] == "barge_in" and eventos[0]["id"] == "p1"
    assert [e["id"] for e in eventos[1:]] == ["p2", "p3"]


async def test_clear_do_nosso_interrupt_nao_apaga_a_fala_seguinte(canal):
    await canal.enviar({"type": "falar", "id": "a", "texto": "Uma.", "interromper": False})
    await canal.enviar({"type": "parar"})
    assert await canal._traduzir({"type": "clear"}) == []


async def test_transcricao_corrigida_e_api_volta_a_ouvir(canal):
    fala = await canal._traduzir({"type": "transcript", "utterance_id": "u1",
                                  "text": "roda o pai teste no cliente ponto py",
                                  "assessment": {"ignore": False, "confirm": True},
                                  "corrections": [{"heard": "daymon", "term": "daemon.py", "score": 0.8}]})
    assert canal.ws.json()[-1] == {"type": "done_processing"}
    assert fala[0]["texto"] == "roda o pytest no cliente.py"
    assert fala[0]["cru"] == "roda o pai teste no cliente ponto py"
    assert fala[0]["incerto"]
    assert {"ouvido": "daymon", "corrigido": "daemon.py", "fonte": "vocabulario"} in fala[0]["correcoes"]


async def test_ruido_nao_vira_fala(canal):
    ev = await canal._traduzir({"type": "transcript", "text": "hm", "assessment": {"ignore": True}})
    assert ev[0]["type"] == "ruido"


async def test_parciais_so_quando_alguem_ve(canal):
    assert await canal._traduzir({"type": "transcript.partial", "text": "roda"}) == []
    await canal.enviar({"type": "opcoes", "parciais": True})
    assert await canal._traduzir({"type": "transcript.partial", "text": "roda"}) == [{"type": "parcial",
                                                                                       "texto": "roda"}]


async def test_modo_comando_falar_por_cima_nao_corta(canal):
    await canal.enviar({"type": "opcoes", "barge_in_palavra": ["Ermis"]})
    await canal.enviar({"type": "falar", "id": "a", "texto": "Oi.", "interromper": False})
    assert canal.ws.json()[-1]["allow_barge_in"] is False


def test_opcoes_da_sessao():
    c = VoiceApi("https://x", "k", paciencia="longa", voz="Bruno", termos=["pytest"])
    op = c._opcoes()
    assert op["transport"] == "websocket" and op["audio_format"] == "pcm16_48k"
    assert op["vad"]["min_silence_ms"] == 1600 and op["voice"] == "Bruno"
    assert op["waiting"]["filler_after_ms"] is None and op["auto_decide"] is False
    assert op["vocabulary"] == ["pytest"]


def test_sem_chave_ou_servidor_antigo_explica_o_que_fazer():
    with pytest.raises(ErroApi, match="app.ermis.ai"):
        VoiceApi("https://x", "")
    with pytest.raises(ErroApi, match="descontinuado"):
        VoiceApi("wss://exemplo.invalid", "k")


def test_erros_http_viram_mensagens_uteis():
    assert "Tokens API" in str(erro_http(401, '{"error": {"code": "invalid_api_key"}}'))
    assert "créditos" in str(erro_http(402, "{}"))
    assert "canais" in str(erro_http(429, '{"error": {"code": "channel_limit"}}'))
    assert erro_http(429, '{"error": {"code": "rate_limited"}}').espera_s == 10.0


def test_velocidade_da_fala_vai_na_sessao_so_quando_muda():
    assert "speech_speed" not in VoiceApi("https://x", "k")._opcoes()
    assert VoiceApi("https://x", "k", velocidade=1.2)._opcoes()["speech_speed"] == 1.2
    assert VoiceApi("https://x", "k", velocidade=3)._opcoes()["speech_speed"] == 1.25
    assert VoiceApi("https://x", "k", velocidade=0.5)._opcoes()["speech_speed"] == 0.75


async def test_api_sem_velocidade_cai_para_a_normal():
    import httpx

    pedidos = []

    def handler(request):
        corpo = json.loads(request.content)
        pedidos.append(corpo)
        if "speech_speed" in corpo:
            return httpx.Response(400, json={"error": "invalid_request", "message": "speech_speed: Extra inputs"})
        return httpx.Response(201, json={"session_id": "vs_1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = VoiceApi("https://x", "k", velocidade=1.2, http=http)
        assert (await c._criar_sessao())["session_id"] == "vs_1"
    assert ["speech_speed" in p for p in pedidos] == [True, False]
