/** Параметры входа приложения на ПК через браузер: `/desktop-login?port=&state=&challenge=`. */
export interface IDesktopLoginParams {
  port: number;
  state: string;
  challenge: string;
}

const STATE_RE = /^[A-Za-z0-9_-]{16,128}$/;
const CHALLENGE_RE = /^[0-9a-f]{64}$/;
const PORT_RE = /^\d{1,5}$/;

/** null — параметры отсутствуют или повреждены. */
export function parseDesktopLoginParams(search: string): IDesktopLoginParams | null {
  const q = new URLSearchParams(search);
  const portRaw = q.get('port') ?? '';
  const state = q.get('state') ?? '';
  const challenge = q.get('challenge') ?? '';
  if (!PORT_RE.test(portRaw) || !STATE_RE.test(state) || !CHALLENGE_RE.test(challenge)) return null;
  const port = Number(portRaw);
  if (port < 1024 || port > 65535) return null;
  return { port, state, challenge };
}

/** Адрес loopback-callback приложения: либо код, либо отказ. */
export function desktopCallbackUrl(
  { port, state }: Pick<IDesktopLoginParams, 'port' | 'state'>,
  result: { code: string } | { error: 'access_denied' },
): string {
  const head = `http://127.0.0.1:${port}/callback`;
  const s = encodeURIComponent(state);
  return 'code' in result
    ? `${head}?code=${encodeURIComponent(result.code)}&state=${s}`
    : `${head}?error=${result.error}&state=${s}`;
}
