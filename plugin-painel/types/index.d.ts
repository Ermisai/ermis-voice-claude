/** O que o daemon do Ermis Voz escreve em ~/.ermis-voz/estado.json (versão 1). */
export type EstadoVoz = {
  versao: number
  /** Quando foi escrito, ms desde a época (o daemon reescreve a cada 2 s). */
  t: number
  estado: 'ouvindo' | 'pessoa_falando' | 'claude_pensando' | 'claude_falando' | 'desconectado' | 'desligado'
  /** Desde quando está nesse estado, ms desde a época. */
  desde: number
  /** O que a pessoa está dizendo agora (STT em streaming). */
  parcial: string
  /** A última fala completa, já corrigida. */
  ultima_fala: string
  /** O que o agente está falando. */
  fala_agente: string
  /** Falas guardadas para o Claude ler depois da próxima ferramenta. */
  pendentes: number
  modo: string
  aec: boolean
  servidor: string
  /** O stream de microfone e alto-falante está rodando (false: caiu, o daemon está reabrindo). */
  audio_ok?: boolean
  /** A palavra-chave do modo comando (configurável; "Ermis" por padrão). */
  palavra?: string
  /** A pasta do projeto em que o daemon foi iniciado. */
  projeto?: string
  /** Segurar o espaço para falar: segurando, ou soltou e a fala está fechando. */
  espaco?: 'segurando' | 'soltou' | null
  /** O último pedido falado ("Ermis, ..." no modo comando, ou segurando o espaço: origem "espaco"); o painel o
   * manda como prompt uma vez. */
  comando?: { id: string; t: number; texto: string; bloco: string; origem?: 'espaco'; aperto?: number | null } | null
}

/** ~/.ermis-voz/ativa.json: a janela do Claude Code em uso (a última em que a pessoa digitou, mandou um prompt ou um
 * comando), renovada a cada 2 s por ela. Só ela mostra a transcrição ao vivo, e o daemon só pede a transcrição ao vivo
 * ao servidor enquanto há uma. */
export type SessaoAtiva = { sessao: string; t: number; cwd: string }

declare module 'claude-code' {
  interface PluginState {
    'ermis-voice-painel': { estado: EstadoVoz | null; ativa: boolean; tecla: boolean }
  }
}
