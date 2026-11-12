---
description: Liga o modo espaço — segure a barra de espaço (com o prompt vazio) para falar; ao soltar, o que você disse vai como prompt
allowed-tools: Bash(ermis-voz modo:*), Bash(ermis-voz status:*)
---

Rode `ermis-voz modo espaco`. Responda em uma frase curta: com o prompt vazio, é só segurar a barra de espaço, falar
e soltar; o que ela disser chega como prompt. Precisa do plugin `ermis-voice-painel` (é ele que vê a tecla).

Como funciona, para você saber: o microfone só vai para a Voice API enquanto o espaço está apertado (e quando você
pergunta algo pela ferramenta `conversar`). O que ela disse chega como uma mensagem dela com `[fala]`
(reconhecimento de voz: entenda termos técnicos pelo contexto). As respostas não são faladas neste modo. Segurar o
espaço funciona também nos outros modos; fora deles (ferramenta ou desligado), o primeiro aperto liga este modo.
Para sair: `/ermis-voice:parar`.
