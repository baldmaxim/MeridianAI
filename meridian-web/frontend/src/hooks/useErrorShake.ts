import { useEffect, useRef } from 'react';

/**
 * useErrorShake — error-state-shake (transitions.dev 12).
 * Возвращает ref на элемент-форму/инпут (нужен класс `t-input`). При каждом
 * инкременте shakeKey перезапускает шейк: снять `.is-shaking` → reflow
 * (`void offsetWidth`) → навесить заново. Reflow обязателен, иначе анимация
 * не переиграется (см. SKILL.md). Reduced-motion гасится CSS-guard'ом.
 *
 *   const [shakeKey, setShakeKey] = useState(0);
 *   const formRef = useErrorShake<HTMLFormElement>(shakeKey);
 *   // на неудачной валидации/ответе: setShakeKey(k => k + 1)
 *   <form ref={formRef} className="t-input">…</form>
 */
export function useErrorShake<T extends HTMLElement = HTMLElement>(shakeKey: number) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (shakeKey === 0) return;
    const el = ref.current;
    if (!el) return;
    el.classList.remove('is-shaking');
    void el.offsetWidth; // reflow для перезапуска анимации
    el.classList.add('is-shaking');
  }, [shakeKey]);
  return ref;
}
