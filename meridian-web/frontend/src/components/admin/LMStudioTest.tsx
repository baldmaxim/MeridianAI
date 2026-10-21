import { useState } from 'react';
import { useTestLmStudio } from '../../hooks/queries/admin';
import type { LMStudioTestResult } from '../../types';
import { errorDetail } from '../../lib/errorDetail';
import styles from './LMStudioTest.module.css';
import { cx } from '../../utils/cx';

export function LMStudioTest() {
  const test = useTestLmStudio();
  const [result, setResult] = useState<LMStudioTestResult | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handleTest = async () => {
    setResult(null);
    setErrMsg(null);
    try {
      setResult(await test.mutateAsync());
    } catch (e) {
      setErrMsg(errorDetail(e) || 'Не удалось проверить связь');
    }
  };

  const expected = result?.expected_present ?? {};

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>LM Studio · локальная машина</span>
      </div>
      <p className={styles.desc}>
        Токен добавляется выше как сервис <code className={styles.code}>lm_studio</code> (хранится
        зашифрованно). Проверка связи запрашивает список моделей сервера.
      </p>

      <button onClick={handleTest} disabled={test.isPending} className={cx('t-btn t-btn-amber', styles.btn)}>
        {test.isPending ? 'Проверка…' : 'Проверить связь'}
      </button>

      {errMsg && <div className={styles.errBox}>{errMsg}</div>}

      {result && !result.ok && (
        <div className={styles.errBox}>
          Ошибка подключения к {result.base_url}: {result.error}
        </div>
      )}

      {result && result.ok && (
        <div className={styles.resultBox}>
          <div className={styles.row}>
            <span className={styles.label}>Base URL</span>
            <span className={styles.value}>{result.base_url}</span>
          </div>
          <div className={styles.badges}>
            {Object.entries(expected).map(([model, present]) => {
              return (
                <span key={model} className={cx(styles.badge, present ? styles.badgeOk : styles.badgeBad)}>
                  {present ? '✓' : '✕'} {model}
                </span>
              );
            })}
          </div>
          {result.models && result.models.length > 0 && (
            <div className={styles.row}>
              <span className={styles.label}>Модели на сервере</span>
              <span className={styles.value}>{result.models.join(', ')}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
