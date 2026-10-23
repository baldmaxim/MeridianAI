/** Версия, чей диалог пользователь уже закрыл («Позже»): повторно сам не открывается. */
export const UPDATE_DISMISSED_KEY = "meridian.update.dismissedVersion";
/** Версия, о которой уже показано системное уведомление. */
export const UPDATE_NOTIFIED_KEY = "meridian.update.notifiedVersion";

/** localStorage может быть недоступен — тогда просто ничего не помним. */
export const readUpdateMemory = (key: string): string | null => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};

export const writeUpdateMemory = (key: string, value: string): void => {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Без хранилища напоминание повторится после перезапуска — не критично.
  }
};
