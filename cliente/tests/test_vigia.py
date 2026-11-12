import asyncio

from ermis_voz.audio_local import Aec, Reproducao
from ermis_voz.config import Config
from ermis_voz.daemon import Daemon


class AudioQueMorre:
    """Um stream que para (como um fone que desconectou) e volta quando reaberto."""

    def __init__(self) -> None:
        self.reproducao = Reproducao()
        self.aec = Aec(False)
        self.mudo = False
        self.dispositivos = ("Mic", "Fone")
        self.reaberturas = 0
        self.erros_callback = 0
        self.ultimo_erro = ""
        self._vivo = True

    def vivo(self) -> bool:
        return self._vivo

    def padrao_mudou(self) -> bool:
        return False

    def reabrir(self) -> None:
        self.reaberturas += 1
        self._vivo = True


async def test_vigia_reabre_o_audio_que_parou(tmp_path, monkeypatch):
    monkeypatch.setenv("ERMIS_VOZ_HOME", str(tmp_path))
    d = Daemon(Config())
    d.audio = AudioQueMorre()
    vigia = asyncio.create_task(d._vigiar_audio())
    await asyncio.sleep(2.2)
    assert d.audio.reaberturas == 0 and d.audio_ok
    d.audio._vivo = False  # o stream morreu
    await asyncio.sleep(2.2)
    vigia.cancel()
    assert d.audio.reaberturas == 1
    assert d.audio_ok
