import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { EstadoVoz, SessaoAtiva } from '../types'

// O daemon (ermis-voz) reescreve o estado a cada mudança e a cada 2 s; mais velho que isto, ele parou
const VELHO_MS = 6000
// A janela ativa renova a marca a cada 2 s; sem renovação por este tempo, nenhuma janela está ativa
const ATIVA_MS = 6000
const estado = atom({ plugin: 'ermis-voice-painel', key: 'estado' } as const, null)
const ativa = atom({ plugin: 'ermis-voice-painel', key: 'ativa' } as const, false)
const tecla = atom({ plugin: 'ermis-voice-painel', key: 'tecla' } as const, false)

// Segurar o espaço (com o prompt vazio) para falar. O terminal não avisa quando a tecla é solta: segurar é ver a
// repetição automática do espaço; soltar é ela parar
const REPETICAO_MS = 900 // sem repetição até aqui, foi um toque (o atraso inicial do macOS vai até ~700 ms)
const SOLTURA_MS = 260 // repetição parada por isto: soltou (o intervalo padrão é 30–90 ms)
type Aperto = { t0: number; ultimo: number; repeticoes: number; gravando: boolean; soltar: boolean }
let aperto: Aperto | null = null
let meuUltimoAperto = 0
let espacoDesligado = false // o comando ermis-voz não existe aqui: o espaço volta a ser só espaço
let filaEspaco: Promise<unknown> = Promise.resolve()

function curto(texto: string, max: number): string {
  const t = texto.replace(/\s+/g, ' ').trim()
  return t.length <= max ? t : `…${t.slice(t.length - max + 1)}`
}

// Fora da janela ativa só o essencial: sem a transcrição e a fala, que mudam o tempo todo e redesenhariam à toa
function resumido(v: EstadoVoz | null): EstadoVoz | null {
  return v === null ? null : { ...v, parcial: '', fala_agente: '', ultima_fala: '', t: Math.floor(v.t / 4000) * 4000 }
}

// Por sessão: cada janela do Claude Code carrega o módulo à parte
let meuId = ''
let pastaAtiva: string | null = null
let ativaPath = ''
let ultimaMarca = 0

// "Esta janela está em uso": a pessoa digitou, mandou um prompt ou um comando, ou abriu a sessão aqui
async function marcar($: EngineInterface, forcar = false): Promise<void> {
  if (!ativaPath || !meuId) {
    return
  }
  const agora = await $.clock.now()
  if (!forcar && agora - ultimaMarca < 1000) {
    return
  }
  ultimaMarca = agora
  const marca: SessaoAtiva = { sessao: meuId, t: agora, cwd: pastaAtiva ?? '' }
  try {
    await $.fs.write(ativaPath, JSON.stringify(marca))
  } catch {
    return
  }
  await update($, ativa, () => true)
}

// O agente falando (ou com falas na fila): o primeiro aperto do espaço já o cala, sem esperar saber se é toque ou
// segurar. Fora da fila de segurar/soltar: é o que precisa ser mais rápido
function calar($: EngineInterface): void {
  void $.process.run(['ermis-voz', 'parar'], { timeoutMs: 10000 }).catch(() => undefined)
}

function espaco($: EngineInterface, acao: 'segurar' | 'soltar', t?: number): void {
  // em ordem: o soltar nunca chega antes do segurar
  filaEspaco = filaEspaco.then(async () => {
    try {
      const argv = ['ermis-voz', 'espaco', acao, ...(t ? ['--t', String(t)] : [])]
      const r = await $.process.run(argv, { timeoutMs: 20000 })
      if (r.exitCode !== 0 && acao === 'segurar') {
        await $.ui.toast(`voz: ${(r.stderr || r.stdout).trim().split('\n').pop() ?? 'falhou'}`)
      }
    } catch {
      espacoDesligado = true
      aperto = null
      await update($, tecla, () => false)
      await $.ui.toast('voz: o comando ermis-voz não foi encontrado; veja o README para instalar o cliente')
    }
  })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const home = await $.env.get('HOME')
    const inicio = await $.clock.now()
    meuId = await $.session.id()
    pastaAtiva = e.cwd
    let ultimoComando = ''
    // segurar o espaço: começa na primeira repetição, solta quando ela para
    $.clock.every(40, async () => {
      const a = aperto
      if (a === null) {
        return
      }
      const agora = await $.clock.now()
      if (!a.gravando) {
        if (a.repeticoes > 0) {
          a.gravando = true
          meuUltimoAperto = a.t0
          await marcar($, true)
          await update($, tecla, () => true)
          espaco($, 'segurar', a.t0)
        } else if (agora - a.t0 > REPETICAO_MS || a.soltar) {
          aperto = null // um toque: nada a fazer (o prompt estava vazio)
        }
        return
      }
      if (a.soltar || agora - a.ultimo > SOLTURA_MS) {
        aperto = null
        await update($, tecla, () => false)
        espaco($, 'soltar')
      }
    })
    if (home !== undefined) {
      const path = `${home}/.ermis-voz/estado.json`
      ativaPath = `${home}/.ermis-voz/ativa.json`
      await marcar($)
      let ultimo = ''
      let tick = 0
      $.clock.every(250, async () => {
        tick += 1
        let souAtiva = await read($, ativa)
        // fora da janela ativa, lê a cada 2 s
        if (!souAtiva && tick % 8 !== 0) {
          return
        }
        let marcaAtiva: SessaoAtiva | null = null
        try {
          marcaAtiva = JSON.parse(await $.fs.read(ativaPath)) as SessaoAtiva
        } catch {
          marcaAtiva = null
        }
        const agora = await $.clock.now()
        const nova = marcaAtiva !== null && marcaAtiva.sessao === meuId
        if (nova !== souAtiva) {
          souAtiva = nova
          await update($, ativa, () => nova)
        }
        if (souAtiva && marcaAtiva !== null && agora - marcaAtiva.t >= 2000) {
          await marcar($, true) // renova: o daemon só pede a transcrição ao vivo enquanto há uma janela ativa
        }
        let texto = ''
        try {
          texto = await $.fs.read(path)
        } catch {
          texto = ''
        }
        let valor: EstadoVoz | null = null
        try {
          valor = texto ? (JSON.parse(texto) as EstadoVoz) : null
        } catch {
          valor = null
        }
        const mostrar = souAtiva ? valor : resumido(valor)
        const chave = JSON.stringify(mostrar)
        if (chave !== ultimo) {
          ultimo = chave
          await update($, estado, () => mostrar)
        }
        // Modo comando: "Ermis, ..." vira um prompt da pessoa, uma vez, depois de a sessão começar (o arquivo guarda o
        // último pedido; reabrir o Claude Code não o repete). Vai para a janela ativa; sem nenhuma ativa, para a
        // janela na pasta do projeto do daemon
        const cmd = valor?.comando
        // Segurar o espaço: o que ela disse vai como prompt para a janela em que ela segurou
        if (cmd && cmd.origem === 'espaco' && cmd.id !== ultimoComando && cmd.t >= inicio) {
          ultimoComando = cmd.id
          if (meuUltimoAperto > 0 && cmd.aperto === meuUltimoAperto) { // só a fala do aperto desta janela
            void $.prompt.submit({ text: cmd.bloco, asUser: true })
          }
        } else if (valor?.modo === 'comando' && cmd && cmd.id !== ultimoComando && cmd.t >= inicio) {
          const algumaAtiva = marcaAtiva !== null && agora - marcaAtiva.t < ATIVA_MS
          const minha = algumaAtiva ? souAtiva : !valor.projeto || valor.projeto === pastaAtiva
          if (minha) {
            ultimoComando = cmd.id
            void $.prompt.submit({ text: cmd.bloco, asUser: true })
          } else if (algumaAtiva) {
            ultimoComando = cmd.id // é de outra janela
          }
        }
      })
    }

    return next(e)
  })

  // O espaço com o prompt vazio não entra no prompt: segurado, ele grava (veja o timer em session.start)
  on('prompt.edit', async ($, e, next) => {
    const soEspacos = e.inputText.length > 0 && /^ +$/.test(e.inputText) && e.start === e.end
    if (!espacoDesligado && soEspacos && (aperto !== null || e.text === '')) {
      const agora = await $.clock.now()
      if (aperto === null) {
        aperto = { t0: agora, ultimo: agora, repeticoes: e.inputText.length - 1, gravando: false, soltar: false }
        const v = await read($, estado)
        if (v !== null && agora - v.t < VELHO_MS && (v.estado === 'claude_falando' || (v.fila ?? 0) > 0)) {
          calar($)
        }
      } else {
        aperto.ultimo = agora
        aperto.repeticoes += e.inputText.length
      }
      return { text: e.text, cursor: e.cursor }
    }
    if (aperto !== null) {
      aperto.soltar = true // outra tecla: soltou o espaço
    }
    return next(e)
  })

  on('prompt.change', async ($, e, next) => {
    await marcar($)
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    await marcar($)
    return next(e)
  })

  on('command.run', async ($, e, next) => {
    await marcar($)
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const v = await read($, estado)
    const segurando = await read($, tecla)
    if (segurando && !e.props.hasSurvey) {
      const { Box, Text } = $.ui.resolve(e)
      const largura = Math.max(20, e.props.bodyColumns - 40)
      const vivo = v !== null && v.estado !== 'desligado' && v.estado !== 'desconectado'
      return (
        <Box>
          <Text color="error" weight="bold">● gravando </Text>
          <Text dimColor>{vivo ? '· solte o espaço para mandar ' : '· ligando a voz… '}</Text>
          <Text wrap="truncate-start">{v?.parcial ? curto(v.parcial, largura) : ''}</Text>
        </Box>
      )
    }
    if (e.props.hasSurvey || v === null || v.estado === 'desligado') {
      return next(e)
    }
    const agora = await $.clock.now()
    if (agora - v.t > VELHO_MS) {
      return next(e)
    }
    const souAtiva = await read($, ativa)

    const { Box, Text } = $.ui.resolve(e)
    if (v.audio_ok === false) {
      return (
        <Box>
          <Text color="warning">○ voz sem áudio no computador: reabrindo o microfone e o alto-falante…</Text>
        </Box>
      )
    }
    const largura = Math.max(20, e.props.bodyColumns - 24)
    const segundos = Math.max(0, Math.round((agora - v.desde) / 1000))

    if (!souAtiva) {
      // outra janela está em uso: só uma linha discreta, sem transcrição
      const onde = v.estado === 'pessoa_falando' ? 'ouvindo você' : v.estado === 'desconectado' ? 'sem conexão' : 'ativa'
      return (
        <Box>
          <Text dimColor>○ voz {onde} · a transcrição aparece na janela em uso</Text>
        </Box>
      )
    }
    if (v.estado === 'pessoa_falando') {
      return (
        <Box>
          <Text color="success" weight="bold">● você: </Text>
          <Text wrap="truncate-start">{v.parcial ? curto(v.parcial, largura) : '…'}</Text>
        </Box>
      )
    }
    if (v.estado === 'claude_pensando') {
      return (
        <Box>
          <Text color="claude" weight="bold">◌ Claude pensando · {segundos} s </Text>
          <Text dimColor wrap="truncate-end">{v.ultima_fala ? `ouvi: ${curto(v.ultima_fala, largura - 6)}` : ''}</Text>
        </Box>
      )
    }
    if (v.estado === 'claude_falando') {
      return (
        <Box>
          <Text color="suggestion" weight="bold">♪ falando: </Text>
          <Text dimColor wrap="truncate-end">{curto(v.fala_agente, largura)}</Text>
        </Box>
      )
    }
    if (v.estado === 'desconectado') {
      return (
        <Box>
          <Text color="warning">○ voz sem conexão com a Voice API ({v.servidor})</Text>
        </Box>
      )
    }
    const extra = v.pendentes > 0 ? ` · ${v.pendentes} fala(s) para o Claude ler` : ''
    const comoOuve =
      v.modo === 'comando'
        ? `comando: diga "${v.palavra ?? 'Ermis'}, …"`
        : v.modo === 'leitura'
          ? 'leitura'
          : v.modo === 'espaco'
            ? 'segure o espaço para falar'
            : 'ouvindo'
    return (
      <Box>
        <Text dimColor>○ {comoOuve}{v.aec ? '' : ' (sem cancelamento de eco)'}{extra} </Text>
        <Text dimColor wrap="truncate-end">{v.ultima_fala ? `· última: ${curto(v.ultima_fala, largura - 20)}` : ''}</Text>
      </Box>
    )
  })
}
