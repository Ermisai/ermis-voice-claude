import { expect, mock, test } from 'claude-code/testing'

const AGORA = 1_800_000_000_000

function arquivo(over: Record<string, unknown>) {
  return JSON.stringify({
    versao: 1, t: AGORA, estado: 'ouvindo', desde: AGORA, parcial: '', ultima_fala: '', fala_agente: '',
    pendentes: 0, modo: 'comando', aec: true, servidor: 'ws://x', projeto: '/proj', comando: null, ...over,
  })
}

// `ativa`: de quem é a marca de janela em uso ("eu", outra sessão, ou nenhuma: null)
function montar(on: Parameters<Parameters<typeof test>[1]>[1], conteudo: () => string, ativa: 'eu' | 'outra' | null) {
  const clock = mock.clock(on, { now: AGORA })
  mock.env(on, { HOME: '/home/eu' })
  const enviados: string[] = []
  let marca: string | null =
    ativa === null ? null : JSON.stringify({ sessao: ativa === 'eu' ? 's-eu' : 's-outra', t: AGORA, cwd: '/proj' })
  const escreveMarca = ativa !== 'outra'
  on('prompt.submit', (_, e) => {
    enviados.push(e.text)
    return { text: e.text }
  })
  on('session.id', () => ({ value: 's-eu' }))
  on('fs.write', (_, e) => {
    if (e.path.endsWith('ativa.json') && escreveMarca) {
      marca = e.text
    }
    return { value: undefined }
  })
  on('fs.read', (_, e) => {
    if (e.path.endsWith('ativa.json')) {
      if (marca === null) {
        throw new Error('ENOENT')
      }
      return { value: ativa === 'outra' ? JSON.stringify({ sessao: 's-outra', t: clock.now(), cwd: '/x' }) : marca }
    }
    return { value: conteudo() }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  return { clock, enviados }
}

const PEDIDO = { id: 'p-1', t: AGORA + 100, texto: 'Roda os testes.', bloco: '[fala] Roda os testes.' }

test('modo comando: o pedido vira um prompt na janela em uso, uma vez só', async ($, on) => {
  let conteudo = arquivo({})
  const { clock, enviados } = montar(on, () => conteudo, 'eu')
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await clock.advance(300)
  expect(enviados).toEqual([])
  conteudo = arquivo({ comando: PEDIDO })
  await clock.advance(300)
  expect(enviados).toEqual(['[fala] Roda os testes.'])
  conteudo = arquivo({ comando: PEDIDO, t: AGORA + 2000 }) // o daemon reescreve o arquivo com o mesmo pedido
  await clock.advance(2000)
  expect(enviados.length).toBe(1)
})

test('modo comando: com outra janela em uso, esta não recebe o pedido', async ($, on) => {
  const { clock, enviados } = montar(on, () => arquivo({ comando: PEDIDO }), 'outra')
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await clock.advance(2500)
  expect(enviados).toEqual([])
})

test('modo comando: um pedido de antes de a sessão abrir não é repetido', async ($, on) => {
  const { clock, enviados } = montar(on, () => arquivo({ comando: { ...PEDIDO, t: AGORA - 60_000 } }), 'eu')
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await clock.advance(300)
  expect(enviados).toEqual([])
})

test('fora do modo comando nada é enviado', async ($, on) => {
  const { clock, enviados } = montar(on, () => arquivo({ modo: 'maos_livres', comando: PEDIDO }), 'eu')
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  await clock.advance(300)
  expect(enviados).toEqual([])
})

test('a janela marca que está em uso ao abrir e quando a pessoa digita', async ($, on) => {
  const escritas: string[] = []
  mock.clock(on, { now: AGORA })
  mock.env(on, { HOME: '/home/eu' })
  on('session.id', () => ({ value: 's-eu' }))
  on('fs.write', (_, e) => {
    escritas.push(e.path)
    return { value: undefined }
  })
  on('fs.read', () => {
    throw new Error('ENOENT')
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/proj', surface: 'terminal', isInteractive: true })
  expect(escritas).toEqual(['/home/eu/.ermis-voz/ativa.json'])
})
