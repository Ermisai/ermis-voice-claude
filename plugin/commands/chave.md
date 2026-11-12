---
description: Salva a sua chave de API da Ermis (criada em app.ermis.ai, Tokens API); ela é conferida antes de salvar
argument-hint: "SUA_CHAVE"
allowed-tools: Bash(ermis-voz chave:*), Bash(ermis-voz status:*)
---

A voz usa a Ermis Voice API com a chave de quem usa: cada pessoa cria a própria em https://app.ermis.ai (menu
**Tokens API**, com acesso ao **Ermis Voice**) e cola aqui. A sessão de voz é cobrada nos créditos dessa conta.

- Com argumento: rode `ermis-voz chave $ARGUMENTS`. Ele confere a chave na Voice API e só salva se valer. Diga em uma
  frase se salvou (e os créditos disponíveis) ou o motivo de não ter salvo. Nunca repita a chave na resposta.
- Sem argumento: não rode nada. Explique como criar a chave e diga que há duas formas de colar: no terminal,
  `ermis-voz chave` (pede a chave sem mostrar na tela e sem passar pela conversa, a mais segura), ou aqui,
  `/ermis-voice:chave SUA_CHAVE`.
- Se o comando não for encontrado, o cliente não está no PATH: diga para rodar
  `uv tool install --force ~/ermis-voz/cliente` e conferir que `~/.local/bin` está no PATH (`uv tool update-shell`).
- Depois de salvar, rode `ermis-voz status` e diga se conectou.
