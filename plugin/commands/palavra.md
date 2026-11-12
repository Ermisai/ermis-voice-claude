---
description: Mostra ou troca a palavra-chave do modo comando (hoje "Ermis"), ex. /ermis-voice:palavra Jarvis
argument-hint: "[nova palavra] [--grafias a,b]"
allowed-tools: Bash(ermis-voz palavra:*)
---

Rode `ermis-voz palavra $ARGUMENTS` e diga em uma frase qual é a palavra-chave agora (e, se mudou, que a pessoa já
pode chamar por ela). Se a pessoa disser que o reconhecimento não pega a palavra nova, sugira acrescentar as grafias
que aparecem errado com `--grafias "x,y"` (no painel ao vivo dá para ver como ela foi ouvida).
