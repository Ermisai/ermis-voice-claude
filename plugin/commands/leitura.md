---
description: Liga o modo leitura — você só ouve as respostas do Claude (resumidas quando longas); o microfone fica desligado
allowed-tools: Bash(ermis-voz modo:*)
---

Rode `ermis-voz modo leitura` e confirme em uma frase curta, sem markdown.

A partir de agora a pessoa ouve suas respostas em voz alta e fala com você pelo teclado (o microfone fica
desligado: nada é transcrito). Abra TODA resposta com um parágrafo de no máximo três frases curtas, em português,
sem código, sem markdown e sem listas, que diga o essencial: o resultado, o que mudou, o que você precisa dela.
Respostas curtas são lidas inteiras; numa longa, ela ouve esse parágrafo e o resto fica na tela (nunca mais de dois
minutos de áudio). Escreva esse parágrafo como se fala: frases completas de até umas vinte palavras, sem parênteses,
siglas desconhecidas, barras ou símbolos, números simples ("dois terços", "uns trinta segundos"). Para sair:
`/ermis-voice:parar`.
