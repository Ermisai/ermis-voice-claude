# Ermis Voice para o Claude Code

Voz em português no Claude Code: você fala, o Claude entende (inclusive termos técnicos, pelo contexto) e responde
em voz alta. Pode interromper falando por cima. A voz (reconhecimento, fim de turno, síntese) é a
[Ermis Voice API](https://voice-api.live.ermis.ai), com a **sua** chave de API da Ermis: cada pessoa cria a própria
chave na plataforma e cola no próprio plugin.

```
 seu computador                                              Ermis Voice API (voice-api.live.ermis.ai)
┌──────────────────────────────────────────────────┐        ┌──────────────────────────────────────┐
│ Claude Code (uma ou várias janelas)              │        │ fim de turno                         │
│  ├─ plugin (skill, comandos, hooks)              │        │ reconhecimento pt-BR + vocabulário   │
│  └─ MCP: conversar / falar / ouvir               │        │ interrupção por voz (barge-in)       │
│ ermis-voz daemon (um por computador)             │  wss   │ voz pt-BR                            │
│  ├─ microfone + alto-falante, cancelamento de eco│ ◄────► │                                      │
│  ├─ fila das falas de todas as janelas           │ μ-law  │ cobrança por segundo de sessão,      │
│  ├─ leitura, frases de espera, narração          │ 8 kHz  │ na conta da sua chave                │
│  └─ texto falável e correção de termos técnicos  │ + JSON │                                      │
└──────────────────────────────────────────────────┘        └──────────────────────────────────────┘
```

## Para quem vai usar

1. **Crie a sua chave de API.** Entre em [app.ermis.ai](https://app.ermis.ai), abra **Tokens API**, crie um token com
   acesso ao **Ermis Voice** e copie. A chave é sua: a sessão de voz é cobrada nos créditos da sua conta.

2. Instale o cliente (macOS ou Linux, Python 3.11+, com [uv](https://docs.astral.sh/uv/)):

   ```sh
   uv tool install "git+https://github.com/Ermisai/ermis-voice-claude#subdirectory=cliente"
   ermis-voz chave        # cole a chave (não aparece na tela); ela é conferida e salva
   ermis-voz testar       # fala uma frase e mostra o que ouviu
   ```

   Na primeira vez o macOS pede permissão de microfone para o terminal. A chave fica em `~/.ermis-voz/config.json`
   (só o seu usuário lê). Dentro do Claude Code também dá: `/ermis-voice:chave SUA_CHAVE`; aí a chave passa
   pela conversa, então prefira o terminal. Se o terminal não achar o `ermis-voz`: `uv tool update-shell`.

3. Instale os plugins no Claude Code:

   ```
   /plugin marketplace add Ermisai/ermis-voice-claude
   /plugin install ermis-voice@ermis
   /plugin install ermis-voice-painel@ermis
   ```

   O `ermis-voice-painel` mostra ao vivo, acima do prompt, o que você está falando e o estado da voz (ouvindo,
   você falando, Claude pensando há N s, o que está sendo falado), e é ele que faz o **segurar o espaço para falar** e
   o modo comando funcionarem. (Sem plugin, só o MCP: `claude mcp add --scope user ermis-voz -- ermis-voz mcp`.)

4. Use:

   | Comando | O que faz |
   |---|---|
   | `/ermis-voice:conversar` | Conversa por voz: o Claude fala e escuta a cada turno (ferramenta `conversar`) |
   | `/ermis-voice:maos-livres` | O começo de cada resposta é falado; o que você responder por voz continua a conversa |
   | `/ermis-voice:leitura` | Só ouvir as respostas (inteiras se curtas, resumidas se longas, até 2 min); o microfone fica desligado |
   | segurar **espaço** | Com o prompt vazio: segure a barra de espaço, fale e solte; o que você disse vai como prompt. Precisa do `ermis-voice-painel` (veja abaixo) |
   | `/ermis-voice:espaco` | Modo espaço: o microfone só abre enquanto você segura o espaço (o primeiro aperto já liga este modo) |
   | `/ermis-voice:comando` | Só o que começa com "Ermis" vira pedido ("Ermis, roda os testes"); a resposta é falada. Precisa do `ermis-voice-painel` |
   | `/ermis-voice:palavra Jarvis` | Troca a palavra-chave do modo comando (mostra a atual sem argumento) |
   | `/ermis-voice:pensamento off` | Liga/desliga a narração do que o Claude pensa e faz (`on`, `off`, `so-pensamento`, `so-progresso`) |
   | `/ermis-voice:parar` | Desliga a voz e fecha o microfone |
   | `/ermis-voice:status` | Conexão, créditos, cancelamento de eco, modo, fila |
   | `/ermis-voice:chave SUA_CHAVE` | Salva a sua chave de API da Ermis (conferida antes) |
   | `/ermis-voice:config` | Mostra ou muda a configuração (chave, paciência, voz, fila, `--set campo=valor`) |

   Dicas: fale normalmente, com pausas; o turno fecha quando você termina a ideia (há paciência para pensar).
   Pode interromper o Claude falando por cima. "Pode parar de ouvir" desliga o modo mãos livres. Enquanto ele
   trabalha, o que você disser chega para ele depois da próxima ferramenta.

## Segurar o espaço para falar

Com o `ermis-voice-painel` instalado e o prompt **vazio**, segure a barra de espaço: a faixa acima do prompt mostra
"● gravando" e o que você está dizendo. Ao soltar, a fala é transcrita e mandada como prompt na janela em que você
segurou. Com texto no prompt, o espaço é só espaço; um toque rápido não grava nada.

- O terminal não avisa quando a tecla é solta: o painel vê a repetição automática do espaço e entende que você
  soltou quando ela para. Se a sua repetição de teclas está muito lenta ou desligada (Ajustes do Sistema → Teclado),
  segurar não é reconhecido.
- O começo da fala não se perde: o daemon guarda os últimos 3 s do microfone (só na memória) e manda desde o aperto.
- Fora dos modos de voz (ferramenta ou desligado), o primeiro aperto liga o modo `espaco`: o microfone fica fechado
  e só vai para a Voice API enquanto você segura o espaço. Sem uso por `ocioso_s`, a sessão fecha (e a cobrança
  para); o próximo aperto abre de novo, o que leva um ou dois segundos (a faixa mostra "ligando a voz…").
- Nos outros modos (mãos livres, comando, leitura) segurar o espaço também funciona: o que você disser enquanto
  segura vai como prompt, em vez de seguir o modo.
- Se o modo de voz nativo do Claude Code (`/voice`) também usa o espaço, desligue um dos dois.

## Custo e privacidade

- Enquanto a voz está ligada, o daemon mantém **uma sessão aberta** na Voice API, cobrada por segundo na conta da
  sua chave, também em silêncio. `ermis-voz sair` (ou `/ermis-voice:parar`) encerra a sessão e a cobrança. No modo
  ferramenta (só a ferramenta `conversar`), o daemon encerra sozinho depois de `ocioso_s` (300 s) sem uso e volta na
  próxima chamada de voz; nos modos mãos livres, comando e leitura fica ligado até você parar. Uma sessão
  dura até 4 horas; depois disso, ou se cair, o daemon abre outra sozinho. `ermis-voz status` mostra os créditos.
- O microfone vai para a Voice API (já sem o eco do alto-falante) enquanto a sessão está aberta, exceto no modo
  leitura: nele o microfone fica mudo e só vai silêncio, para a sessão não expirar.
- No computador fica só o log do daemon (`~/.ermis-voz/daemon.log`), sem áudio e sem o texto falado. Os últimos 3 s
  do microfone ficam só na memória, para o segurar o espaço não cortar o começo da fala.
- O áudio é processado pela Voice API da Ermis e não é guardado: veja os [Termos de Serviço](https://www.ermis.ai/terms),
  a [Política de Privacidade](https://www.ermis.ai/privacy) e [onde ficam os dados](https://www.ermis.ai/trust).
  Este plugin não grava nem envia áudio para nenhum outro lugar.
- Os nomes do projeto (arquivos, símbolos, dependências; até 200) vão como `vocabulary` da sessão, para o
  reconhecimento acertar "daemon.py" e "pytest". O resumo de respostas longas usa a sua `ANTHROPIC_API_KEY`, se houver.

## Várias janelas do Claude ao mesmo tempo

Um daemon por computador atende todas as janelas do Claude Code, e a voz fala **uma coisa por vez**:

- A fala nova de uma janela corta a fala em curso **da mesma janela** (a resposta nova substitui a velha), nunca a de
  outra: a outra janela espera a vez.
- Só a mais nova de cada janela espera: se ela pedir de novo enquanto espera, a anterior sai da fila.
- No máximo `fila_max` (3) falas esperam. Quando enche, sai a mais antiga (fica no log como `fila: descartado`); o
  Claude daquela janela recebe `[não falado]` quando esperava resposta (`conversar`). Mude com
  `ermis-voz config --set fila_max=5`.
- Depois que você interrompe, a fila espera você terminar de falar. `/ermis-voice:parar` cala a fala e esvazia a fila.
- `ermis-voz status` mostra o que está falando (`falando`), a fila (`fila`) e quantas foram descartadas.

## Configuração

`/ermis-voice:config` no Claude Code ou `ermis-voz config` no terminal. Sem argumentos mostra tudo (a chave como
`***`); com argumentos muda e vale na hora (se o endereço ou a chave mudaram, o daemon abre uma sessão nova):

```sh
ermis-voz chave                                    # troca a chave (conferida antes de salvar)
ermis-voz vozes                                    # as vozes da sua conta
ermis-voz config --paciencia longa --voz Bruno
ermis-voz config --set preenchimento=false --set leitura_max_s=60          # qualquer campo do config.json
ermis-voz config --set "frases_preenchimento=Um momento.|Deixa eu ver."     # listas separadas por |
```

Os campos ficam em `~/.ermis-voz/config.json`: `servidor` (o endereço da Voice API; o padrão é
`https://voice-api.live.ermis.ai`), `token` (a sua chave), `paciencia` (`rapida` | `normal` | `longa`: o silêncio que
fecha o seu turno, 0,5, 0,9 ou 1,6 s; o fim de turno da API fecha antes quando você terminou a ideia; vale a partir da
próxima sessão), `voz`, `aec` (`webrtc` | `nenhum`), `entrada`/`saida` (nomes de `ermis-voz dispositivos`),
`barge_in`, `fila_max`, as frases de espera, a palavra-chave, a narração e a leitura (abaixo). Uma variável
`VOZ_<CAMPO>` no ambiente tem prioridade sobre o arquivo. Se o terminal não achar o `ermis-voz`, o `~/.local/bin`
não está no PATH: `uv tool update-shell`.

Frases de espera (ligadas por padrão): quando o Claude demora a responder depois de uma fala sua, toca uma frase
curta ("Hum, deixa eu ver.") aos `preenchimento_ms` (900) e uma de paciência aos `paciencia_ms` (12000; 0 desliga);
qualquer fala do Claude, ou você voltando a falar, cancela. Desligar: `"preenchimento": false`. As frases ficam em
`frases_preenchimento` e `frases_paciencia` (no ambiente, separadas por `|`).

Modo leitura: só ouvir. O microfone fica mudo (nada é transcrito, gravado nem mandado ao Claude) e cada resposta é
lida pelo cliente: inteira, em partes por parágrafo, se couber em `leitura_inteiro_ate_s` (45 s); se não, um resumo
de ~`leitura_resumo_s` (60 s), nesta ordem: a abertura da própria resposta (no modo leitura o Claude é instruído a
abrir toda resposta com um parágrafo de até três frases que diga o essencial; de graça), o Claude Haiku 5.5 (com
`ANTHROPIC_API_KEY` no ambiente e o pacote `anthropic` instalado; também traduz respostas em inglês) e, sem nada disso, um resumo extrativo (a frase
principal de cada parágrafo). Nunca passa de `leitura_max_s` (120 s): o resto vira "O resto está na tela.". Blocos de
código e tabelas não são lidos ("Tem código na tela."). Os avisos do Claude Code são traduzidos ("O Claude está
esperando você."); avisos em inglês desconhecidos não são falados. Enquanto o Claude trabalha, a leitura também fala
o que ele vai fazendo ("Vou rodar os testes…", a mesma narração do pensamento dos outros modos), ligado por padrão:
`ermis-voz pensamento leitura-off` (ou `/ermis-voice:pensamento leitura-off`) desliga só na leitura, `leitura-on` liga
de novo; a resposta final corta a narração em curso.

Transcrição ao vivo só onde alguém vê: o painel marca a janela do Claude Code em uso (a última em que você digitou,
mandou um prompt ou um comando) em `~/.ermis-voz/ativa.json`. Só ela mostra a transcrição; as outras mostram uma linha
discreta e leem o estado 8 vezes menos. O daemon só repassa a transcrição ao vivo com uma janela em uso e fora do modo leitura. No modo comando, o
pedido "Ermis, ..." vai para a janela em uso.

Interrupção sem corte seco: quando a Voice API percebe que é você falando por cima, o agente apaga em ~150 ms, sem
clique.

Modo comando (`ermis-voz modo comando` ou `/ermis-voice:comando`): só o que começa com a palavra-chave vira pedido; o
resto é ignorado (fica no log como `ignorada_sem_palavra`), exceto a resposta a uma pergunta que o próprio Claude
fez pela ferramenta `conversar`. "Ermis." sozinho responde "Pode falar." e a próxima fala, começada em até 8 s, vale como
pedido. O pedido entra no Claude Code como mensagem sua, pelo `ermis-voice-painel`.
No modo comando, falar por cima do agente não o corta (é o modo para quando há conversa na sala). Limite da Voice
API: o que é dito sobre uma fala que não aceita interrupção é descartado, então um "Ermis, para" dito por cima também
não chega; espere a fala acabar ou use `/ermis-voice:parar`. O reconhecimento escreve "Ermis" como "Hermes", "Termes",
"herme" e outras formas: a lista está em `cliente/ermis_voz/chave.py` (dá para acrescentar com `--grafias` e trocar a
palavra).

Palavra-chave personalizável: `ermis-voz palavra Jarvis` (ou `/ermis-voice:palavra Jarvis`) vale na hora, no comando,
no painel e nas instruções ao Claude. Além das grafias listadas ("Ermis" tem as medidas;
para outra palavra, acrescente com `--grafias "jarvis,jarbis"`), vale uma palavra parecida (até 1 letra de diferença
a cada 5, sem contar um "h" no começo) quando vem como chamada, com vírgula depois: "Jarbis, abre o arquivo". Palavras
comuns ("mesmo", "temos", "atrás"…) nunca contam.

Narração do pensamento (ligada por padrão; `ermis-voz pensamento off` desliga): enquanto o Claude trabalha, o daemon
acompanha a transcrição da sessão (o caminho vem dos hooks) e fala, resumido à primeira frase, o resumo do raciocínio
(`falar_pensamento`; o Claude Code grava texto em ~1/3 dos blocos de thinking, os outros vêm vazios) e o que ele diz
antes de usar uma ferramenta (`falar_progresso`). No máximo uma a cada `pensamento_intervalo_s` (5 s), sempre a mais
recente (velha de 10 s, descarta); nunca enquanto você fala; pensamento em inglês não é falado (a voz é pt-BR); a
resposta de verdade corta a narração na hora. O texto final continua com o hook Stop.

O que o Claude responde vira texto falável no cliente antes de ir para a voz (números por extenso, unidades,
versões, horas, datas, moeda, símbolos, siglas, identificadores de código, pronúncia de termos em inglês):
`cliente/ermis_voz/fala.py`, `falavel.py` e `pronuncia.py`.

**Fone de ouvido ou alto-falante:** o cancelamento de eco (AEC3 do WebRTC, com a referência exata do que tocou)
deixa usar o alto-falante do notebook. Com Bluetooth em modo de chamada (HFP) a qualidade cai; prefira o microfone
do notebook ou um fone com fio. Se o Claude se interromper sozinho, use `ermis-voz config --aec webrtc` e confira
em `/ermis-voice:status`.

## Quando a voz não conecta

`ermis-voz status` mostra `conectado` e, se não, o motivo em `erro`:

| `erro` | O que fazer |
|---|---|
| falta a chave de API / chave inválida ou revogada | Crie uma chave em app.ermis.ai (Tokens API, com acesso ao Ermis Voice) e rode `ermis-voz chave` |
| créditos insuficientes | Recarregue a conta em app.ermis.ai |
| todos os canais do seu plano estão em uso | Outra máquina sua está com a voz ligada: `ermis-voz sair` nela, ou mude de plano |
| sem conexão com a Voice API | Rede; o daemon tenta de novo sozinho |

## Quando não sai áudio

O daemon vigia o áudio: se o microfone e o alto-falante param (fone Bluetooth que conectou ou desconectou, saída
trocada no macOS, erro no áudio), ele reabre sozinho nos dispositivos padrão em até ~2 s, e o painel mostra "voz sem
áudio no computador" enquanto isso. Se ainda assim não sair som:

```sh
ermis-voz status          # audio.ok, audio.dispositivos, audio.reaberturas, versao
tail -50 ~/.ermis-voz/daemon.log
ermis-voz sair            # o daemon sobe de novo na próxima chamada de voz, com o áudio reaberto
```

`ermis-voz dispositivos` lista os dispositivos; `ermis-voz config --entrada "..." --saida "..."` fixa um (aí o vigia
não troca para o padrão).

## Como a fala chega ao Claude

```
[fala] Roda o pytest no cliente.py e depois faz o commit.
[ouvido cru] roda o pai teste no cliente ponto py e depois faz o commit
[incerto] o reconhecimento ficou em dúvida
```

A Voice API corrige pelo vocabulário da sessão (os nomes do projeto e os pares que o Claude ensina pelo parâmetro
`correcoes`); o cliente corrige o resto de forma determinística (termos de programação ditos em português,
extensões: `cliente/ermis_voz/texto.py`). `[incerto]` aparece quando a API marca a fala como duvidosa. O resto da
correção é o próprio Claude, pelo contexto, sem chamada extra: a skill pede que ele comece com "Entendi: ..." quando
corrigir algo e que confirme ações destrutivas na dúvida.

## Limitações conhecidas

- A fala dita no primeiro segundo da sessão às vezes se perde, e quando você começa a falar por cima do agente as
  primeiras palavras podem não entrar na transcrição.
- O microfone vai para a Voice API em qualidade de telefone (μ-law 8 kHz): frases curtas e soltas são as que mais erram.
- Falar por cima de uma fala que não aceita interrupção é descartado (afeta o modo comando).
- A paciência é fixada na criação da sessão (o parâmetro `paciencia` do `conversar` não muda a sessão em curso).
- Voz e reconhecimento em português do Brasil.

## Desenvolvimento

- `cliente/` (daemon, MCP, hooks, CLI), `plugin/` (comandos, skill, hooks) e `plugin-painel/` (o mod do Claude Code
  que desenha a faixa e vê o espaço segurado). O canal com a Voice API é `cliente/ermis_voz/voice_api.py` (sessão
  `transport: "websocket"`, μ-law 8 kHz de ida, PCM16 48 kHz de volta); a fila é `cliente/ermis_voz/daemon.py`.
- Testes do cliente: `cd cliente && uv run --extra dev python -m pytest`. Do painel: `claude plugin test plugin-painel`.
- Para testar uma mudança local: `uv tool install --force --editable ./cliente` e
  `/plugin marketplace add /caminho/para/ermis-voice-claude`.

## Licença

[MIT](LICENSE). O código é aberto; o uso da Ermis Voice API segue os [Termos de Serviço](https://www.ermis.ai/terms)
e é cobrado na conta da sua chave.
