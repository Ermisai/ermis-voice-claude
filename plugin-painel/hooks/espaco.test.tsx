import { expect, mock, test } from 'claude-code/testing'

const AGORA = 1_800_000_000_000

function arquivo(over: Record<string, unknown>) {
  return JSON.stringify({
    versao: 1, t: AGORA, estado: 'ouvindo', desde: AGORA, parcial: '', ultima_fala: '', fala_agente: '',
    pendentes: 0, modo: 'espaco', aec: true, servidor: 'ws://x', projeto: '/proj', comando: null, ...over,
  })
}

function montar(on: Parameters<Parameters<typeof test>[1]>[1], conteudo: () => string) {
  const clock = mock.clock(on, { now: AGORA })
  mock.env(on, { HOME: '/home/eu' })
  const comandos: string[][] = []
  const enviados: string[] = []
  on('process.run', (_, e) => {
    comandos.push([...e.argv])
    return { value: { exitCode: 0, stdout: '{"ok": true}', stderr: '' } }
  })
  on('prompt.submit', (_, e) => {
    enviados.push(e.text)
    return { text: e.text }
  })
  on('session.id', () => ({ value: 's-eu' }))
  on('fs.write', () => ({ value: undefined }))
  on('fs.read', (_, e) => {
    if (e.path.endsWith('ativa.json')) {
      return { value: JSON.stringify({ sessao: 's-eu', t: clock.now(), cwd: '/proj' }) }
    }
    return { value: conteudo() }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('prompt.edit', (_, e) => ({ text: e.text.slice(0, e.start) + e.inputText + e.text.slice(e.end), cursor: e.start + e.inputText.length }))
  return { clock, comandos, enviados }
}

function espaco(texto = '') {
  return { origin: { kind: 'composer' as const }, key: { key: ' ' }, text: texto, cursor: texto.length,
    start: texto.length, end: texto.length, inputText: ' ' }
}

test('segurar o espaço grava; soltar manda; a fala vira um prompt', async ($, on) => {
  let conteudo = arquivo({})
  const { clock, comandos, enviados } = montar(on, () => conteudo)
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  // aperto e a repetição automática do terminal: nada entra no prompt
  expect(await $.prompt.edit(espaco())).toEqual({ text: '', cursor: 0 })
  for (let i = 0; i < 10; i++) {
    await clock.advance(50)
    expect(await $.prompt.edit(espaco())).toEqual({ text: '', cursor: 0 })
  }
  expect(comandos[0]?.slice(0, 3)).toEqual(['ermis-voz', 'espaco', 'segurar'])
  expect(comandos[0]?.[4]).toBe(String(AGORA))
  // soltou: a repetição parou
  await clock.advance(400)
  expect(comandos.map(c => c[2])).toEqual(['segurar', 'soltar'])
  conteudo = arquivo({ comando: { id: 'e-1', t: clock.now(), texto: 'Roda os testes.', bloco: '[fala] Roda os testes.', origem: 'espaco', aperto: AGORA } })
  await clock.advance(300)
  expect(enviados).toEqual(['[fala] Roda os testes.'])
})

test('um toque no espaço não grava nada', async ($, on) => {
  const { clock, comandos } = montar(on, () => arquivo({}))
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await $.prompt.edit(espaco())
  await clock.advance(1500)
  expect(comandos).toEqual([])
})

test('com texto no prompt o espaço é só espaço', async ($, on) => {
  const { clock, comandos } = montar(on, () => arquivo({}))
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  expect(await $.prompt.edit(espaco('roda'))).toEqual({ text: 'roda ', cursor: 5 })
  await clock.advance(1500)
  expect(comandos).toEqual([])
})

test('uma fala de espaço que não é deste aperto não é enviada', async ($, on) => {
  let conteudo = arquivo({})
  const { clock, enviados } = montar(on, () => conteudo)
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await $.prompt.edit(espaco())
  await clock.advance(50)
  await $.prompt.edit(espaco())
  await clock.advance(400)
  // outro processo (um teste, outra janela) escreveu uma fala de espaço depois do aperto
  conteudo = arquivo({ comando: { id: 'x-1', t: clock.now(), texto: 'Oi.', bloco: '[fala] Oi.', origem: 'espaco', aperto: AGORA + 1 } })
  await clock.advance(300)
  expect(enviados).toEqual([])
})

test('a fala de um aperto em outra janela não é enviada aqui', async ($, on) => {
  const { clock, enviados } = montar(on, () =>
    arquivo({ comando: { id: 'e-2', t: AGORA + 100, texto: 'Oi.', bloco: '[fala] Oi.', origem: 'espaco' } }))
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await clock.advance(600)
  expect(enviados).toEqual([])
})

test('com o agente falando, o primeiro aperto do espaço já o cala', async ($, on) => {
  const { comandos } = montar(on, () => arquivo({ estado: 'claude_falando', fala_agente: 'Rodei os testes.' }))
  on('state.get', (_, e) => ({
    value: { value: e.key === 'estado' ? JSON.parse(arquivo({ estado: 'claude_falando' })) : false, version: 1 },
  }))
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await $.prompt.edit(espaco())
  expect(comandos[0]).toEqual(['ermis-voz', 'parar'])
})

test('sem o agente falando, um toque não cala nada', async ($, on) => {
  const { clock, comandos } = montar(on, () => arquivo({}))
  on('state.get', (_, e) => ({ value: { value: e.key === 'estado' ? JSON.parse(arquivo({})) : false, version: 1 } }))
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await $.prompt.edit(espaco())
  await clock.advance(1500)
  expect(comandos).toEqual([])
})
