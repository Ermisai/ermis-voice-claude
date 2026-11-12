"""O Duplex com um sounddevice falso: o Mac de testes não tem microfone."""

import asyncio
import sys
import time
import types

import numpy as np

from ermis_voz import audio_local


class StreamFalso:
    def __init__(self, callback, finished_callback=None, **kw):
        self.callback = callback
        self.finished = finished_callback
        self.active = False
        self.device = (0, 1)

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def stop(self):
        self.active = False

    def close(self):
        self.active = False


def _sd_falso():
    sd = types.SimpleNamespace()
    sd.Stream = StreamFalso
    sd.query_devices = lambda dev=None, kind=None: {"name": {0: "Mic", 1: "Fone", None: "Fone"}.get(dev, "Fone")
                                                    if kind is None else ("Mic" if kind == "input" else "Fone")}
    sd._terminate = lambda: None
    sd._initialize = lambda: None
    return sd


async def test_callback_com_erro_nao_derruba_e_vigia_reabre(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _sd_falso())
    recebidos = []
    d = audio_local.Duplex(recebidos.append, asyncio.get_running_loop(), aec=False)
    d.iniciar()
    assert d.dispositivos == ("Mic", "Fone")
    entrada = np.zeros((audio_local.BLOCK, 1), dtype=np.float32)
    saida = np.zeros((audio_local.BLOCK, 1), dtype=np.float32)
    info = types.SimpleNamespace(outputBufferDacTime=0.03, inputBufferAdcTime=0.0)
    d.stream.callback(entrada, saida, audio_local.BLOCK, info, None)
    await asyncio.sleep(0)
    assert recebidos and d.vivo()
    # um erro dentro do callback não sai dele (sairia e mataria o stream)
    d.decimador = None
    d.stream.callback(entrada, saida, audio_local.BLOCK, info, None)
    assert d.erros_callback == 1 and np.all(saida == 0)
    # sem callback por mais de 2 s: não está vivo; reabrir volta
    d.ultimo_callback = time.monotonic() - 3
    assert not d.vivo()
    d.decimador = audio_local.Decimador()
    d.reabrir()
    assert d.vivo() and d.reaberturas == 1
