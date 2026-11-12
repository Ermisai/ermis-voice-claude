---
description: Liga o modo comando — só o que começa com "Ermis" vira pedido ("Ermis, roda os testes"); a resposta é falada
allowed-tools: Bash(ermis-voz modo:*), Bash(ermis-voz status:*)
---

Rode `ermis-voz modo comando` e depois `ermis-voz status` (o daemon sobe sozinho se não estiver rodando; se o status
falhar, rode `ermis-voz testar`). Responda em uma frase curta, sem markdown, que ela vai ouvir: diga que é só
começar com "Ermis" e falar o pedido.

Como funciona, para você saber: a partir de agora a pessoa fala com você começando por "Ermis"; o pedido chega como
uma mensagem dela com `[fala]` (sem a palavra-chave), mandada pelo plugin `ermis-voice-painel`, que precisa estar
instalado. O que não começa com "Ermis" é ignorado, exceto quando você mesmo perguntou algo pela ferramenta
`conversar`. O começo de cada resposta sua é falado em voz alta: abra com uma ou duas frases curtas, sem código e sem
markdown (veja a skill `voz`). Para sair: `/ermis-voice:parar`.
