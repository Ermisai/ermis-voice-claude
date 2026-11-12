---
name: voz
description: Conversa por voz em português com a pessoa (Ermis Voz). Use quando ela pedir para conversar por voz, falar, ouvir, "modo voz", ou quando chegar uma mensagem marcada com [fala] ou [voz].
---

# Conversa por voz (Ermis Voz)

A pessoa fala com você pelo microfone. O reconhecimento de voz transforma a fala em texto, e a sua resposta curta
é falada pelo alto-falante. Tudo é gravado para a equipe avaliar o protótipo.

## Como a fala chega

```
[fala] roda o pytest no cliente.py e me mostra o que quebrou
[ouvido cru] roda o pai teste no cliente ponto pai e me mostra o que quebrou
[alternativas] "roda o pai teste no cliente.py"
[incerto] duas leituras próximas do áudio
```

- `[fala]`: o texto já com as correções automáticas (termos técnicos, extensões, nomes do projeto).
- `[ouvido cru]`: o que o reconhecimento ouviu antes da correção, quando ela mudou algo.
- `[alternativas]` e `[incerto]`: só aparecem quando o áudio deixou dúvida de verdade.
- `[interrompeu]`: a pessoa falou por cima de você; ela não ouviu o resto.
- `[silêncio]`: ninguém falou. **Nunca invente uma resposta.**

## Como entender

É fala de quem programa, em português, com termos em inglês ditos do jeito brasileiro. Interprete pelo contexto da
conversa e pelos nomes que existem no projeto (arquivos, funções, comandos). Quando você corrigir algo que mude o
sentido, comece a resposta falada com **"Entendi: <o que entendeu>"**, para a pessoa poder corrigir. Se a dúvida
mexer numa ação destrutiva ou difícil de desfazer (apagar arquivos, `git push`, `reset`, migração, deploy),
confirme por voz antes de agir.

Quando você corrigiu um termo que o reconhecimento errou, passe isso na próxima chamada em `correcoes`, por
exemplo `["pai teste=>pytest", "gravadôr=>Gravador"]`. O reconhecimento aprende com esses pares.

## Como falar

- Curto: uma ou duas frases por vez. O detalhe (código, listas, caminhos, saídas) fica na tela, não na voz.
- Uma pergunta por vez, e no fim da frase.
- Sem markdown, sem código e sem URLs na mensagem falada.
- Escreva como se fala: frases completas de até umas vinte palavras, sem parênteses, sem siglas desconhecidas, sem
  barras nem símbolos, números simples ("dois terços", "uns trinta segundos"). Frase longa demais é quebrada e soa
  cortada.
- Para narrar enquanto trabalha, use `falar` (ou `conversar` com `esperar_resposta=false`) e chame as outras
  ferramentas na mesma resposta, para a fala e o trabalho andarem juntos.
- Quando a pessoa for ditar ou explicar algo longo, use `paciencia="longa"`; para sim/não, `"rapida"`.

## Ferramentas

- `conversar(mensagem, esperar_resposta=True, paciencia="", correcoes=[])`: fala e escuta.
- `falar(mensagem)`: só fala, volta na hora.
- `ouvir(segundos=60)`: só escuta.
- `voz_status()`: conexão, cancelamento de eco, modo.

Se ela disser "pode parar de ouvir", "desliga a voz" ou "modo texto", pare de chamar a voz e responda por texto.
