import { useState } from 'react';
import type { FC } from 'react';
import { requestDesktopBrowserCode } from '../api/desktop';
import { apiErrorMessage } from '../lib/apiError';
import { desktopCallbackUrl, parseDesktopLoginParams } from '../lib/desktopLogin';
import styles from './DesktopLoginPage.module.css';

interface IProps {
  email: string;
}

type Outcome = 'allowed' | 'denied' | null;

export const DesktopLoginPage: FC<IProps> = ({ email }) => {
  // Параметры не меняются за жизнь страницы: разбираем один раз.
  const [params] = useState(() => parseDesktopLoginParams(window.location.search));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [outcome, setOutcome] = useState<Outcome>(null);

  const allow = async () => {
    if (!params) return;
    setBusy(true);
    setError('');
    try {
      const code = await requestDesktopBrowserCode(params.challenge);
      setOutcome('allowed');
      window.location.assign(desktopCallbackUrl(params, { code }));
    } catch (err) {
      setError(apiErrorMessage(err, 'Не удалось получить доступ. Попробуйте ещё раз.'));
      setBusy(false);
    }
  };

  const cancel = () => {
    if (!params) return;
    setBusy(true);
    setOutcome('denied');
    window.location.assign(desktopCallbackUrl(params, { error: 'access_denied' }));
  };

  const renderBody = () => {
    if (!params) {
      return (
        <p className={styles.text} role="alert">
          Ссылка входа устарела или повреждена. Начните вход заново в приложении.
        </p>
      );
    }
    if (outcome === 'allowed') {
      return <p className={styles.text}>Готово. Вернитесь в приложение — вкладку можно закрыть.</p>;
    }
    if (outcome === 'denied') {
      return <p className={styles.text}>Вход отменён.</p>;
    }
    return (
      <>
        <p className={styles.text}>
          Разрешить приложению на этом компьютере доступ к аккаунту <b className={styles.email}>{email}</b>?
        </p>
        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.actions}>
          <button type="button" className={styles.primaryBtn} onClick={allow} disabled={busy}>
            Разрешить
          </button>
          <button type="button" className={styles.ghostBtn} onClick={cancel} disabled={busy}>
            Отмена
          </button>
        </div>
      </>
    );
  };

  return (
    <div className={styles.container}>
      <div className={styles.brandText}>
        MERIDI<span className={styles.brandAccent}>AN</span>
      </div>
      <div className={styles.card}>
        <h1 className={styles.title}>Вход в приложение Meridian для ПК</h1>
        {renderBody()}
      </div>
    </div>
  );
};
