import { expect, test } from 'claude-code/testing'

const AGORA = 1_800_000_000_000

const BAND = {
  plugin: 'ermis-voice-painel',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

function estado(over: Record<string, unknown>) {
  return {
    versao: 1, t: AGORA - 500, estado: 'ouvindo', desde: AGORA - 3000, parcial: '', ultima_fala: '',
    fala_agente: '', pendentes: 0, modo: 'ferramenta', aec: true, servidor: 'ws://x', ...over,
  }
}

function seed(on: Parameters<Parameters<typeof test>[1]>[1], value: unknown, ativa = true) {
  on('state.get', (_, e) => ({ value: { value: e.key === 'ativa' ? ativa : e.key === 'tecla' ? false : value, version: 1 } }))
  on('clock.now', () => ({ value: AGORA }))
}

test('janela que não está em uso: sem a transcrição ao vivo', async ($, on) => {
  seed(on, estado({ estado: 'pessoa_falando', parcial: 'roda o pytest no cliente' }), false)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /pytest/ })).toBe(undefined)
  expect((await ui.find({ type: 'Text', text: /janela em uso/ }))?.text).toBe(
    '○ voz ouvindo você · a transcrição aparece na janela em uso',
  )
  await ui.unmount()
})

test('áudio caído no computador aparece como aviso', async ($, on) => {
  seed(on, estado({ audio_ok: false }))
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /sem áudio/ }))?.text).toBe(
    '○ voz sem áudio no computador: reabrindo o microfone e o alto-falante…',
  )
  await ui.unmount()
})

test('modo leitura aparece como leitura', async ($, on) => {
  seed(on, estado({ modo: 'leitura' }))
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /leitura/ }))?.text).toBe('○ leitura ')
  await ui.unmount()
})

test('mostra o que a pessoa está falando', async ($, on) => {
  seed(on, estado({ estado: 'pessoa_falando', parcial: 'roda o pytest no cliente' }))
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /você/ }))?.text).toBe('● você: ')
  expect((await ui.find({ type: 'Text', text: /pytest/ }))?.text).toBe('roda o pytest no cliente')
  await ui.unmount()
})

test('mostra o Claude pensando, com o tempo e o que ouviu', async ($, on) => {
  seed(on, estado({ estado: 'claude_pensando', ultima_fala: 'Roda o pytest.' }))
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /pensando/ }))?.text).toBe('◌ Claude pensando · 3 s ')
  expect((await ui.find({ type: 'Text', text: /ouvi/ }))?.text).toBe('ouvi: Roda o pytest.')
  await ui.unmount()
})

test('mostra o que o agente está falando', async ($, on) => {
  seed(on, estado({ estado: 'claude_falando', fala_agente: 'Hum, deixa eu ver.' }))
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /deixa/ }))?.text).toBe('Hum, deixa eu ver.')
  await ui.unmount()
})

test('modo comando mostra a palavra-chave configurada', async ($, on) => {
  seed(on, estado({ modo: 'comando', palavra: 'Jarvis' }))
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /comando/ }))?.text).toBe('○ comando: diga "Jarvis, …" ')
  await ui.unmount()
})

test('some quando o daemon parou de escrever (estado velho)', async ($, on) => {
  seed(on, estado({ t: AGORA - 60_000, estado: 'pessoa_falando', parcial: 'oi' }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('some com a voz desligada', async ($, on) => {
  seed(on, estado({ estado: 'desligado' }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})
