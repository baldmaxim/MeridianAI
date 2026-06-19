import { useState, useEffect, useCallback, useRef } from 'react';
import { getSettings, updateSettings as apiUpdateSettings, getActiveProviders } from '../api/settings';
import { useMeetingStore } from '../store/meetingStore';
import { STTSettings } from '../components/settings/STTSettings';
import { LLMSettings } from '../components/settings/LLMSettings';
import { HintsSettings } from '../components/settings/HintsSettings';
import { StorageSettings } from '../components/settings/StorageSettings';
import { theme } from '../styles/theme';
import type { UserSettings, SuggestionTypeConfig, TriggerKeywordConfig } from '../types';

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
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [section, setSection] = useState('stt');
  const [activeServices, setActiveServices] = useState<string[]>();
  const [applying, setApplying] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const setCustomSuggestionTypes = useMeetingStore((s) => s.setCustomSuggestionTypes);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  useEffect(() => {
    getSettings().then(setSettings).catch(() => {});
    getActiveProviders().then(setActiveServices).catch(() => {});
  }, []);

  const handleApply = useCallback(async () => {
    if (!settings || applying) return;
    setApplying(true);
    try {
      await apiUpdateSettings(settings);
      setCustomSuggestionTypes(settings.custom_suggestion_types);
      showToast('Настройки сохранены', 'success');
    } catch {
      showToast('Ошибка сохранения настроек', 'error');
    } finally {
      setApplying(false);
    }
  }, [settings, applying, setCustomSuggestionTypes, showToast]);

  return (
    <div style={embedded ? styles.containerEmbedded : styles.container}>
      {!embedded && (
        <div style={styles.topBar}>
          <button onClick={onBack} className="t-btn" style={styles.backBtn}>&larr; Назад</button>
          <span style={styles.topTitle}>НАСТРОЙКИ</span>
        </div>
      )}

      {!settings ? (
        <div style={styles.loading}>Загрузка...</div>
      ) : (
        <div className="settings-layout mobile-content-pad" style={styles.settingsLayout}>
          <nav style={styles.settingsNav}>
            {SETTINGS_SECTIONS.map((sec) => (
              <button
                key={sec.id}
                onClick={() => setSection(sec.id)}
                className="t-btn"
                style={section === sec.id ? styles.navActive : styles.navItem}
              >
                <span style={{ fontSize: 14 }}>{sec.icon}</span> {sec.label}
              </button>
            ))}
          </nav>
          <div style={styles.settingsContent}>
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
            {section === 'storage' && (
              <StorageSettings
                localPath={settings.local_storage_path || ''}
                onChange={(path) => setSettings({ ...settings, local_storage_path: path })}
              />
            )}
            {section === 'notifications' && (
              <PlaceholderSection title="Уведомления" text="Звуковые уведомления, push-нотификации, уровни важности. Раздел в разработке." />
            )}
            {section === 'locale' && (
              <PlaceholderSection title="Язык и регион" text="Язык интерфейса, формат даты и валюты. Раздел в разработке." />
            )}
            <button
              onClick={handleApply}
              disabled={applying}
              className="t-btn t-btn-amber"
              style={{ ...styles.applyBtn, opacity: applying ? 0.6 : 1, cursor: applying ? 'wait' : 'pointer' }}
            >
              {applying ? 'Сохранение...' : 'Применить настройки'}
            </button>
          </div>
        </div>
      )}

      {toast && (
        <div
          key={toast.message + String(toast.type)}
          style={{
            ...styles.toast,
            borderColor: toast.type === 'success' ? theme.accent.green : theme.accent.red,
            background: toast.type === 'success' ? 'rgba(46,229,157,0.12)' : 'rgba(255,75,110,0.12)',
          }}
        >
          <span style={{
            width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
            background: toast.type === 'success' ? theme.accent.green : theme.accent.red,
          }} />
          <span style={{
            color: toast.type === 'success' ? theme.accent.green : theme.accent.red,
            fontSize: 12, fontFamily: theme.font.mono, fontWeight: 500,
          }}>
            {toast.message}
          </span>
        </div>
      )}
    </div>
  );
}

function PlaceholderSection({ title, text }: { title: string; text: string }) {
  return (
    <div style={styles.placeholderCard}>
      <div style={styles.sectionHeader}>
        <span style={styles.dot} />
        <span style={styles.sectionTitle}>{title}</span>
      </div>
      <div style={styles.placeholderText}>{text}</div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', padding: '20px 24px' },
  containerEmbedded: { display: 'flex', flexDirection: 'column' },
  topBar: {
    display: 'flex', alignItems: 'center', gap: 16,
    paddingBottom: 12, marginBottom: 20,
    borderBottom: `1px solid ${theme.border.default}`, flexShrink: 0,
  },
  backBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 16px',
    background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em', flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.mono, fontSize: 11, fontWeight: 500,
    letterSpacing: '0.16em', color: theme.text.secondary, flex: 1,
  },
  loading: { color: theme.text.secondary, fontFamily: theme.font.mono, fontSize: 13, padding: '20px 0' },
  settingsLayout: { display: 'flex', gap: 24 },
  settingsNav: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 220, flexShrink: 0 },
  navActive: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: theme.accent.amber, color: '#080A0F', border: 'none', borderRadius: 8,
    fontSize: 12, fontWeight: 600, fontFamily: theme.font.body, cursor: 'pointer', textAlign: 'left' as const,
  },
  navItem: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: 'transparent', color: theme.text.secondary, border: 'none', borderRadius: 8,
    fontSize: 12, fontFamily: theme.font.body, cursor: 'pointer', textAlign: 'left' as const,
  },
  settingsContent: { flex: 1, display: 'flex', flexDirection: 'column', gap: 20 },
  placeholderCard: {
    background: theme.bg.card, border: `1px solid ${theme.border.default}`,
    borderRadius: 12, padding: 24, display: 'flex', flexDirection: 'column', gap: 12,
  },
  placeholderText: { color: theme.text.muted, fontSize: 13, fontFamily: theme.font.body, lineHeight: 1.6 },
  sectionHeader: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  sectionTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary, flex: 1,
  },
  applyBtn: {
    marginTop: 8, padding: '9px 22px', background: theme.accent.amber, border: 'none',
    borderRadius: 7, color: '#080A0F', cursor: 'pointer', fontSize: 12, fontWeight: 600,
    fontFamily: theme.font.body, alignSelf: 'flex-start',
  },
  toast: {
    position: 'fixed' as const, bottom: 24, right: 24, zIndex: 9999,
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 18px',
    borderRadius: 8, border: '1px solid', backdropFilter: 'blur(12px)',
    animation: 'toastSlideIn 0.3s ease-out',
  },
};
