import { useState, useCallback, useRef } from 'react';
import { useSettings, useActiveProviders, useUpdateSettings } from '../hooks/queries/settings';
import { useMeetingStore } from '../store/meetingStore';
import { STTSettings } from '../components/settings/STTSettings';
import { LLMSettings } from '../components/settings/LLMSettings';
import { HintsSettings } from '../components/settings/HintsSettings';
import { StorageSettings } from '../components/settings/StorageSettings';
import { RoleSettings } from '../components/settings/RoleSettings';
import { SettingsPlaceholderSection } from '../components/settings/SettingsPlaceholderSection';
import type { UserSettings, SuggestionTypeConfig, TriggerKeywordConfig } from '../types';
import styles from './SettingsPage.module.css';
import { cx } from '../utils/cx';

// Цвета типов подсказок — пользовательские данные (hex хранится в настройках и правится через input[type=color]),
// поэтому здесь остаются hex-значения, а не токены темы.
const DEFAULT_SUGGESTION_TYPES: SuggestionTypeConfig[] = [
  { key: 'priority', badge: '✦ ПРИОРИТЕТ', color: '#F5A623', metaLabel: 'Контекст', actionLabel: 'Использовать', llm_description: 'главная рекомендация: что сказать/сделать ПРЯМО СЕЙЧАС. Учитывай фазу переговоров.', enabled: true },
  { key: 'counter', badge: '⇄ КОНТРАРГУМЕНТ', color: '#5B9CF6', metaLabel: 'Триггер', actionLabel: 'Использовать', secondaryAction: 'Подробнее', llm_description: 'контраргумент на последнее утверждение оппонента. Используй: переформулирование, вопрос-ловушку или «условную уступку».', enabled: true },
  { key: 'question', badge: '? ВОПРОС-ЗАЦЕП', color: '#2EE59D', metaLabel: 'Метод', actionLabel: 'Использовать', llm_description: 'вопрос для перехвата инициативы. Применяй: «калибровочные вопросы», вопросы-якоря, или зеркалирование.', enabled: true },
  { key: 'risk', badge: '⚠ РИСК', color: '#FF4B6E', metaLabel: 'Паттерн', actionLabel: 'Принял к сведению', llm_description: 'предупреждение: что оппонент пытается протащить, какую ловушку расставляет, какой пункт нужно зафиксировать.', enabled: true },
];

const DEFAULT_TRIGGER_KEYWORDS: TriggerKeywordConfig[] = [
  { keyword: 'цена', status_message: 'Анализирую возражение по цене...', enabled: true },
  { keyword: 'срок', status_message: 'Анализирую обсуждение сроков...', enabled: true },
  { keyword: 'гарантия', status_message: 'Анализирую вопрос гарантий...', enabled: true },
  { keyword: 'штраф', status_message: 'Анализирую вопрос штрафных санкций...', enabled: true },
  { keyword: 'договор', status_message: 'Анализирую обсуждение договора...', enabled: true },
  { keyword: 'обсуждаем', status_message: 'Анализирую текущую тему...', enabled: true },
  { keyword: 'ваше мнение', status_message: 'Анализирую запрос мнения...', enabled: true },
  { keyword: 'смета', status_message: 'Анализирую обсуждение сметы...', enabled: true },
  { keyword: 'аванс', status_message: 'Анализирую вопрос авансирования...', enabled: true },
  { keyword: 'материалы', status_message: 'Анализирую обсуждение материалов...', enabled: true },
];

const SETTINGS_SECTIONS = [
  { id: 'stt', icon: '\u{1F399}', label: 'Распознавание речи' },
  { id: 'llm', icon: '\u{1F916}', label: 'Языковая модель' },
  { id: 'roles', icon: '\u{1F3AD}', label: 'Роли переговоров' },
  { id: 'hints', icon: '⚡', label: 'Подсказки' },
  { id: 'storage', icon: '\u{1F4C1}', label: 'Хранилище' },
  { id: 'notifications', icon: '\u{1F514}', label: 'Уведомления' },
  { id: 'locale', icon: '\u{1F310}', label: 'Язык и регион' },
] as const;

interface Props {
  onBack?: () => void;
  embedded?: boolean;
}

export function SettingsPage({ onBack, embedded }: Props) {
  // server-данные кэшируются (мгновенно при повторном заходе); локальная копия — для редактирования
  const { data: serverSettings } = useSettings();
  const { data: activeServices } = useActiveProviders();
  const updateMut = useUpdateSettings();
  const applying = updateMut.isPending;

  // эффективная копия для редактирования: локальные правки поверх кэша/сервера (без seed-эффекта)
  const [edited, setEdited] = useState<UserSettings | null>(null);
  const settings = edited ?? serverSettings ?? null;
  const setSettings = setEdited;
  const [section, setSection] = useState('stt');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const setCustomSuggestionTypes = useMeetingStore((s) => s.setCustomSuggestionTypes);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const handleApply = useCallback(async () => {
    if (!settings || applying) return;
    try {
      await updateMut.mutateAsync(settings);
      setCustomSuggestionTypes(settings.custom_suggestion_types);
      showToast('Настройки сохранены', 'success');
    } catch {
      showToast('Ошибка сохранения настроек', 'error');
    }
  }, [settings, applying, updateMut, setCustomSuggestionTypes, showToast]);

  return (
    <div className={cx(embedded ? styles.containerEmbedded : styles.container)}>
      {!embedded && (
        <div className={styles.topBar}>
          <button onClick={onBack} className={cx('t-btn', styles.backBtn)}>&larr; Назад</button>
          <span className={styles.topTitle}>НАСТРОЙКИ</span>
        </div>
      )}

      {!settings ? (
        <div className={styles.loading}>Загрузка...</div>
      ) : (
        <div className={cx('settings-layout mobile-content-pad', styles.settingsLayout)}>
          <nav className={styles.settingsNav}>
            {SETTINGS_SECTIONS.map((sec) => (
              <button
                key={sec.id}
                onClick={() => setSection(sec.id)}
                className={cx('t-btn', section === sec.id ? styles.navActive : styles.navItem)}
              >
                <span className={styles.navIcon}>{sec.icon}</span> {sec.label}
              </button>
            ))}
          </nav>
          <div className={styles.settingsContent}>
            {section === 'stt' && (
              <STTSettings
                value={settings.stt_provider}
                onChange={(v) => setSettings({ ...settings, stt_provider: v })}
                useStreaming={settings.use_streaming}
                onStreamingChange={(v) => setSettings({ ...settings, use_streaming: v })}
                diarization={settings.diarization}
                onDiarizationChange={(v) => setSettings({ ...settings, diarization: v })}
                silenceFilter={settings.silence_filter}
                onSilenceFilterChange={(v) => setSettings({ ...settings, silence_filter: v })}
                activeServices={activeServices}
              />
            )}
            {section === 'llm' && (
              <LLMSettings
                model={settings.llm_model}
                temperature={settings.temperature}
                onModelChange={(m) => setSettings({ ...settings, llm_model: m })}
                onTemperatureChange={(t) => setSettings({ ...settings, temperature: t })}
                activeServices={activeServices}
              />
            )}
            {section === 'hints' && (
              <HintsSettings
                suggestionTypes={settings.custom_suggestion_types || DEFAULT_SUGGESTION_TYPES}
                triggerKeywords={settings.custom_trigger_keywords || DEFAULT_TRIGGER_KEYWORDS}
                onSuggestionTypesChange={(types) => setSettings({ ...settings, custom_suggestion_types: types })}
                onTriggerKeywordsChange={(keywords) => setSettings({ ...settings, custom_trigger_keywords: keywords })}
              />
            )}
            {section === 'roles' && <RoleSettings />}
            {section === 'storage' && (
              <StorageSettings
                localPath={settings.local_storage_path || ''}
                onChange={(path) => setSettings({ ...settings, local_storage_path: path })}
              />
            )}
            {section === 'notifications' && (
              <SettingsPlaceholderSection title="Уведомления" text="Звуковые уведомления, push-нотификации, уровни важности. Раздел в разработке." />
            )}
            {section === 'locale' && (
              <SettingsPlaceholderSection title="Язык и регион" text="Язык интерфейса, формат даты и валюты. Раздел в разработке." />
            )}
            {section !== 'roles' && (
              <button
                onClick={handleApply}
                disabled={applying}
                className={cx('t-btn t-btn-amber', styles.applyBtn)}
              >
                {applying ? 'Сохранение...' : 'Применить настройки'}
              </button>
            )}
          </div>
        </div>
      )}

      {toast && (
        <div
          key={toast.message + String(toast.type)}
          className={cx(styles.toast, toast.type === 'success' ? styles.toastSuccess : styles.toastError)}
        >
          <span className={styles.toastDot} />
          <span className={styles.toastText}>
            {toast.message}
          </span>
        </div>
      )}
    </div>
  );
}
