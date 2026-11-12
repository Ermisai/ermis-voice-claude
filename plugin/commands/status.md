---
description: Mostra o estado da voz (conexão com a Voice API, créditos, cancelamento de eco, modo, fila)
allowed-tools: Bash(ermis-voz status:*), Bash(ermis-voz modo:*)
---

Rode `ermis-voz modo` e `ermis-voz status` e resuma em poucas linhas: conectado ou não (e o motivo, do campo `erro`),
créditos, cancelamento de eco ligado ou não, modo atual, o que está falando e quantas falas esperam na fila. Se o
`erro` falar de chave, diga para criar uma em app.ermis.ai (Tokens API) e usar `/ermis-voice:chave`. Se o daemon não
estiver rodando, diga que ele sobe sozinho na primeira chamada de voz.
