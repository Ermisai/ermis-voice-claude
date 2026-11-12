---
description: Mostra ou muda a configuração da voz (chave, paciência, voz, fila, frases de espera, leitura…); vale na hora
argument-hint: "[--voz NOME] [--velocidade 0.75-1.25] [--paciencia rapida|normal|longa] [--set campo=valor ...]"
allowed-tools: Bash(ermis-voz config:*), Bash(ermis-voz status:*), Bash(ermis-voz vozes:*)
---

Rode `ermis-voz config $ARGUMENTS` (sem argumentos, só mostra a configuração; a chave aparece como `***`).

- A chave de API (campo `token`) se troca com `/ermis-voice:chave`, que confere antes de salvar.
- Para trocar a voz, `ermis-voz vozes` lista as da conta; depois `--voz NOME`.
- Velocidade da fala: `--velocidade` de 0.75 (mais devagar) a 1.25 (mais rápido); 1 é a normal. "Fala mais rápido"
  vira `--velocidade 1.15` (e mais um pouco a cada pedido, até 1.25); "mais devagar", `--velocidade 0.9`. Vale na
  próxima sessão de voz, e só quando a Voice API já tiver a velocidade da fala; antes disso a voz segue na normal.
- Várias janelas do Claude falando: `--set fila_max=N` (quantas falas esperam a vez).

- Se a pessoa pediu uma mudança em palavras ("deixa mais paciente", "desliga a frase de espera", "lê no máximo um
  minuto"), traduza para as opções: `--paciencia longa`; `--set preenchimento=false`; `--set leitura_max_s=60`.
  Os campos estão na saída do próprio comando; listas vão separadas por `|`
  (`--set "frases_preenchimento=Um momento.|Deixa eu ver."`).
- Se o comando não for encontrado, o cliente não está no PATH: diga para rodar
  `uv tool install --force ~/ermis-voz/cliente` e conferir que `~/.local/bin` está no PATH (`uv tool update-shell`).
- Depois de mudar, rode `ermis-voz status` e diga em uma frase se está conectado e o que mudou. Não mostre o token.
