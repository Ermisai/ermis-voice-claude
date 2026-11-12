---
description: Liga ou desliga a narração falada do que o Claude pensa e faz enquanto trabalha (on | off | so-pensamento | so-progresso | leitura-on | leitura-off)
argument-hint: "[on|off|so-pensamento|so-progresso|leitura-on|leitura-off]"
allowed-tools: Bash(ermis-voz pensamento:*)
---

Rode `ermis-voz pensamento $ARGUMENTS` e confirme em uma frase como ficou. "on" fala o resumo do raciocínio e o que
você diz antes de usar uma ferramenta; "off" desliga os dois; "so-pensamento" e "so-progresso" deixam um só; "leitura-off" desliga a narração só no modo leitura e "leitura-on" a liga de novo.
