import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useMeetingStore } from '../store/meetingStore';
import { getSettings, updateSettings as apiUpdateSettings, getActiveProviders } from '../api/settings';
import { createMeeting } from '../api/meetings';
import { getLiveState } from '../api/mobile';
import { QRCodeSVG } from 'qrcode.react';
import type { LiveState } from '../types';
import { ChatDisplay } from '../components/meeting/ChatDisplay';
import { SuggestionPanel } from '../components/meeting/SuggestionPanel';
import { ControlButtons } from '../components/meeting/ControlButtons';
import { MeetingStats } from '../components/meeting/MeetingStats';
import { ConversationTreePanel } from '../components/meeting/ConversationTreePanel';
import { getConversationTree } from '../api/conversationTree';
import { PopNumber } from '../components/common/PopNumber';
import { MeetingDocuments } from '../components/context/MeetingDocuments';
import { FinalizationPanel } from '../components/protocol/FinalizationPanel';
import { MeetingContext } from '../components/context/MeetingContext';
import { RolesTab } from '../components/context/RolesTab';
import { STTSettings } from '../components/settings/STTSettings';
import { LLMSettings } from '../components/settings/LLMSettings';
import { HintsSettings } from '../components/settings/HintsSettings';
import { StorageSettings } from '../components/settings/StorageSettings';
import { theme } from '../styles/theme';
import type { UserSettings, SuggestionTypeConfig, TriggerKeywordConfig } from '../types';

const DEFAULT_SUGGESTION_TYPES: SuggestionTypeConfig[] = [
  { key: 'priority', badge: '\u2726 \u041F\u0420\u0418\u041E\u0420\u0418\u0422\u0415\u0422', color: '#F5A623', metaLabel: '\u041A\u043E\u043D\u0442\u0435\u043A\u0441\u0442', actionLabel: '\u0418\u0441\u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u044C', llm_description: '\u0433\u043B\u0430\u0432\u043D\u0430\u044F \u0440\u0435\u043A\u043E\u043C\u0435\u043D\u0434\u0430\u0446\u0438\u044F: \u0447\u0442\u043E \u0441\u043A\u0430\u0437\u0430\u0442\u044C/\u0441\u0434\u0435\u043B\u0430\u0442\u044C \u041F\u0420\u042F\u041C\u041E \u0421\u0415\u0419\u0427\u0410\u0421. \u0423\u0447\u0438\u0442\u044B\u0432\u0430\u0439 \u0444\u0430\u0437\u0443 \u043F\u0435\u0440\u0435\u0433\u043E\u0432\u043E\u0440\u043E\u0432.', enabled: true },
  { key: 'counter', badge: '\u21C4 \u041A\u041E\u041D\u0422\u0420\u0410\u0420\u0413\u0423\u041C\u0415\u041D\u0422', color: '#5B9CF6', metaLabel: '\u0422\u0440\u0438\u0433\u0433\u0435\u0440', actionLabel: '\u0418\u0441\u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u044C', secondaryAction: '\u041F\u043E\u0434\u0440\u043E\u0431\u043D\u0435\u0435', llm_description: '\u043A\u043E\u043D\u0442\u0440\u0430\u0440\u0433\u0443\u043C\u0435\u043D\u0442 \u043D\u0430 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0435\u0435 \u0443\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043D\u0438\u0435 \u043E\u043F\u043F\u043E\u043D\u0435\u043D\u0442\u0430. \u0418\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0439: \u043F\u0435\u0440\u0435\u0444\u043E\u0440\u043C\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435, \u0432\u043E\u043F\u0440\u043E\u0441-\u043B\u043E\u0432\u0443\u0448\u043A\u0443 \u0438\u043B\u0438 \u00AB\u0443\u0441\u043B\u043E\u0432\u043D\u0443\u044E \u0443\u0441\u0442\u0443\u043F\u043A\u0443\u00BB.', enabled: true },
  { key: 'question', badge: '? \u0412\u041E\u041F\u0420\u041E\u0421-\u0417\u0410\u0426\u0415\u041F', color: '#2EE59D', metaLabel: '\u041C\u0435\u0442\u043E\u0434', actionLabel: '\u0418\u0441\u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u044C', llm_description: '\u0432\u043E\u043F\u0440\u043E\u0441 \u0434\u043B\u044F \u043F\u0435\u0440\u0435\u0445\u0432\u0430\u0442\u0430 \u0438\u043D\u0438\u0446\u0438\u0430\u0442\u0438\u0432\u044B. \u041F\u0440\u0438\u043C\u0435\u043D\u044F\u0439: \u00AB\u043A\u0430\u043B\u0438\u0431\u0440\u043E\u0432\u043E\u0447\u043D\u044B\u0435 \u0432\u043E\u043F\u0440\u043E\u0441\u044B\u00BB, \u0432\u043E\u043F\u0440\u043E\u0441\u044B-\u044F\u043A\u043E\u0440\u044F, \u0438\u043B\u0438 \u0437\u0435\u0440\u043A\u0430\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435.', enabled: true },
  { key: 'risk', badge: '\u26A0 \u0420\u0418\u0421\u041A', color: '#FF4B6E', metaLabel: '\u041F\u0430\u0442\u0442\u0435\u0440\u043D', actionLabel: '\u041F\u0440\u0438\u043D\u044F\u043B \u043A \u0441\u0432\u0435\u0434\u0435\u043D\u0438\u044E', llm_description: '\u043F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0435: \u0447\u0442\u043E \u043E\u043F\u043F\u043E\u043D\u0435\u043D\u0442 \u043F\u044B\u0442\u0430\u0435\u0442\u0441\u044F \u043F\u0440\u043E\u0442\u0430\u0449\u0438\u0442\u044C, \u043A\u0430\u043A\u0443\u044E \u043B\u043E\u0432\u0443\u0448\u043A\u0443 \u0440\u0430\u0441\u0441\u0442\u0430\u0432\u043B\u044F\u0435\u0442, \u043A\u0430\u043A\u043E\u0439 \u043F\u0443\u043D\u043A\u0442 \u043D\u0443\u0436\u043D\u043E \u0437\u0430\u0444\u0438\u043A\u0441\u0438\u0440\u043E\u0432\u0430\u0442\u044C.', enabled: true },
];

const DEFAULT_TRIGGER_KEYWORDS: TriggerKeywordConfig[] = [
  { keyword: '\u0446\u0435\u043D\u0430', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u0432\u043E\u0437\u0440\u0430\u0436\u0435\u043D\u0438\u0435 \u043F\u043E \u0446\u0435\u043D\u0435...', enabled: true },
  { keyword: '\u0441\u0440\u043E\u043A', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u043E\u0431\u0441\u0443\u0436\u0434\u0435\u043D\u0438\u0435 \u0441\u0440\u043E\u043A\u043E\u0432...', enabled: true },
  { keyword: '\u0433\u0430\u0440\u0430\u043D\u0442\u0438\u044F', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u0432\u043E\u043F\u0440\u043E\u0441 \u0433\u0430\u0440\u0430\u043D\u0442\u0438\u0439...', enabled: true },
  { keyword: '\u0448\u0442\u0440\u0430\u0444', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u0432\u043E\u043F\u0440\u043E\u0441 \u0448\u0442\u0440\u0430\u0444\u043D\u044B\u0445 \u0441\u0430\u043D\u043A\u0446\u0438\u0439...', enabled: true },
  { keyword: '\u0434\u043E\u0433\u043E\u0432\u043E\u0440', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u043E\u0431\u0441\u0443\u0436\u0434\u0435\u043D\u0438\u0435 \u0434\u043E\u0433\u043E\u0432\u043E\u0440\u0430...', enabled: true },
  { keyword: '\u043E\u0431\u0441\u0443\u0436\u0434\u0430\u0435\u043C', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u0442\u0435\u043A\u0443\u0449\u0443\u044E \u0442\u0435\u043C\u0443...', enabled: true },
  { keyword: '\u0432\u0430\u0448\u0435 \u043C\u043D\u0435\u043D\u0438\u0435', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u0437\u0430\u043F\u0440\u043E\u0441 \u043C\u043D\u0435\u043D\u0438\u044F...', enabled: true },
  { keyword: '\u0441\u043C\u0435\u0442\u0430', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u043E\u0431\u0441\u0443\u0436\u0434\u0435\u043D\u0438\u0435 \u0441\u043C\u0435\u0442\u044B...', enabled: true },
  { keyword: '\u0430\u0432\u0430\u043D\u0441', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u0432\u043E\u043F\u0440\u043E\u0441 \u0430\u0432\u0430\u043D\u0441\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u044F...', enabled: true },
  { keyword: '\u043C\u0430\u0442\u0435\u0440\u0438\u0430\u043B\u044B', status_message: '\u0410\u043D\u0430\u043B\u0438\u0437\u0438\u0440\u0443\u044E \u043E\u0431\u0441\u0443\u0436\u0434\u0435\u043D\u0438\u0435 \u043C\u0430\u0442\u0435\u0440\u0438\u0430\u043B\u043E\u0432...', enabled: true },
];

const TABS = ['Переговоры', 'Контекст встречи', 'Настройки'] as const;

const SETTINGS_SECTIONS = [
  { id: 'stt', icon: '\u{1F399}', label: 'Распознавание речи' },
  { id: 'llm', icon: '\u{1F916}', label: 'Языковая модель' },
  { id: 'hints', icon: '\u26A1', label: 'Подсказки' },
  { id: 'roles', icon: '\u{1F465}', label: 'Роли' },
  { id: 'storage', icon: '\u{1F4C1}', label: 'Хранилище' },
  { id: 'notifications', icon: '\u{1F514}', label: 'Уведомления' },
  { id: 'locale', icon: '\u{1F310}', label: 'Язык и регион' },
] as const;

export function MeetingPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [settingsSection, setSettingsSection] = useState('stt');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeServices, setActiveServices] = useState<string[]>();
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const { connect, disconnect, sendJSON, sendBinary } = useWebSocket();
  const { start: startAudio, stop: stopAudio } = useAudioRecorder(sendBinary);
  const store = useMeetingStore();

  // Этап 2/3: обеспечить meeting_id (draft) и подключиться как desktop.
  // forceNew=true — начать НОВУЮ встречу без reload (Этап 3, замечание о finalize).
  const startSession = useCallback(async (forceNew = false) => {
    if (forceNew) {
      disconnect();
      useMeetingStore.getState().newMeetingSession();
    }
    const st = useMeetingStore.getState();
    let id = st.draftMeetingId ?? st.meetingSavedId ?? null;
    if (id == null) {
      try {
        const m = await createMeeting({
          customer_id: st.selectedCustomerId,
          object_id: st.selectedObjectId,
          meeting_topic: st.meetingTopic || null,
          meeting_notes: st.meetingNotes || null,
          negotiation_type: st.negotiationType || null,
          meeting_role: st.meetingRole || null,
          opponent_weaknesses: st.opponentWeaknesses || null,
        });
        id = m.id;
        st.setDraftMeetingId(m.id);
      } catch {
        // draft не создан — подключимся через legacy endpoint
      }
    }
    if (id != null) st.setCurrentMeetingId(id);
    connect(id != null ? { meetingId: id, deviceRole: 'desktop' } : undefined);
  }, [connect, disconnect]);

  useEffect(() => {
    startSession(false);
    getSettings().then((s) => {
      setSettings(s);
      store.setCustomSuggestionTypes(s.custom_suggestion_types);
    }).catch(() => {});
    getActiveProviders().then(setActiveServices).catch(() => {});
    return () => { disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Этап 3: лёгкий поллинг live-состояния для блока «Телефон-диктофон»
  const [liveState, setLiveState] = useState<LiveState | null>(null);
  useEffect(() => {
    if (store.currentMeetingId == null) return;
    const id = store.currentMeetingId;
    const tick = () => getLiveState(id).then(setLiveState).catch(() => {});
    tick();
    const t = setInterval(tick, 4000);
    return () => clearInterval(t);
  }, [store.currentMeetingId]);

  // Conversation Tree: начальная загрузка дерева при открытии встречи
  useEffect(() => {
    if (store.currentMeetingId == null) return;
    getConversationTree(store.currentMeetingId)
      .then((tree) => store.setConversationTree(tree.topics, tree.tree_version, tree.unassigned_speakers))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.currentMeetingId]);

  // Перезагружать провайдеров при переключении на вкладку настроек
  useEffect(() => {
    if (activeTab === 2) {
      getActiveProviders().then(setActiveServices).catch(() => {});
    }
  }, [activeTab]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (store.isListening || store.messages.length > 0) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [store.isListening, store.messages.length]);

  // Hotkeys: Space — toggle listening, H — suggestion, S — strengthen
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (e.code === 'Space') {
        e.preventDefault();
        if (store.isListening) {
          stopAudio();
          sendJSON({ type: 'stop_audio' });
          store.setListening(false);
        } else if (store.isConnected) {
          const st = useMeetingStore.getState();
          if (st.activeAudioSource && st.activeAudioSource !== st.connectionId) {
            store.setError('Источник аудио занят (идёт запись с телефона)');
          } else {
            startAudio().then(() => {
              sendJSON({ type: 'start_audio' });
              store.setListening(true);
            }).catch(() => store.setError('Не удалось получить доступ к микрофону'));
          }
        }
      } else if (e.code === 'KeyH' && !e.ctrlKey && !e.metaKey) {
        if (store.isConnected && !store.suggestionLoading) {
          sendJSON({ type: 'request_suggestion' });
        }
      } else if (e.code === 'KeyS' && !e.ctrlKey && !e.metaKey) {
        if (store.isConnected && !store.strengthenLoading) {
          sendJSON({ type: 'strengthen_position' });
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [store.isListening, store.isConnected, store.suggestionLoading, store.strengthenLoading, startAudio, stopAudio, sendJSON]);

  const handleStartListening = useCallback(async () => {
    // Этап 3: если активный источник аудио — другое устройство (телефон), не стартуем
    const st = useMeetingStore.getState();
    if (st.activeAudioSource && st.activeAudioSource !== st.connectionId) {
      store.setError('Источник аудио занят (идёт запись с телефона)');
      return;
    }
    try {
      await startAudio();
      sendJSON({ type: 'start_audio' });
      store.setListening(true);
    } catch {
      store.setError('Не удалось получить доступ к микрофону');
    }
  }, [startAudio, sendJSON]);

  const handleStopListening = useCallback(() => {
    stopAudio();
    sendJSON({ type: 'stop_audio' });
    store.setListening(false);
  }, [stopAudio, sendJSON]);

  const handleContextChange = useCallback((topic: string, notes: string, negotiationType: string, meetingRole: string, opponentWeaknesses: string) => {
    sendJSON({ type: 'update_meeting_context', title: store.meetingName || undefined, topic, notes, negotiation_type: negotiationType, meeting_role: meetingRole, opponent_weaknesses: opponentWeaknesses });
  }, [sendJSON, store.meetingName]);

  const handleMeetingNameChange = useCallback((name: string) => {
    store.setMeetingName(name);
    sendJSON({ type: 'update_meeting_context', title: name, topic: store.meetingTopic, notes: store.meetingNotes, negotiation_type: store.negotiationType, meeting_role: store.meetingRole, opponent_weaknesses: store.opponentWeaknesses });
  }, [sendJSON, store.meetingTopic, store.meetingNotes, store.negotiationType, store.meetingRole, store.opponentWeaknesses]);

  const [savingMeeting, setSavingMeeting] = useState(false);

  const handleSaveMeeting = useCallback(() => {
    if (savingMeeting) return;
    setSavingMeeting(true);
    sendJSON({ type: 'finalize_meeting', meeting_name: store.meetingName || undefined });
    showToast('Встреча сохранена', 'success');
    setTimeout(() => setSavingMeeting(false), 2000);
  }, [sendJSON, store.meetingName, savingMeeting, showToast]);

  const handleRoleSelect = useCallback((roleId: number) => {
    sendJSON({ type: 'change_role', role_id: roleId });
  }, [sendJSON]);

  const [applyingSettings, setApplyingSettings] = useState(false);

  const handleApplySettings = useCallback(async () => {
    if (!settings || applyingSettings) return;
    setApplyingSettings(true);
    try {
      await apiUpdateSettings(settings);
      sendJSON({
        type: 'change_settings',
        stt_provider: settings.stt_provider,
        llm_model: settings.llm_model,
        temperature: settings.temperature,
        diarization: settings.diarization,
        silence_filter: settings.silence_filter,
        custom_suggestion_types: settings.custom_suggestion_types,
        custom_trigger_keywords: settings.custom_trigger_keywords,
      } as any);
      // Update store so SuggestionPanel uses new types
      store.setCustomSuggestionTypes(settings.custom_suggestion_types);
      showToast('Настройки успешно применены', 'success');
    } catch {
      showToast('Ошибка сохранения настроек', 'error');
    } finally {
      setApplyingSettings(false);
    }
  }, [settings, sendJSON, applyingSettings, showToast]);

  return (
    <div style={styles.container}>
      {/* Tab bar */}
      <div className="meeting-tabs" style={styles.tabs}>
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            style={{
              ...styles.tab,
              borderBottom: activeTab === i ? `2px solid ${theme.accent.amber}` : '2px solid transparent',
              color: activeTab === i ? theme.accent.amber : theme.text.muted,
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={activeTab === 0 ? styles.contentNegotiations : styles.content}>
        {/* Переговоры */}
        {activeTab === 0 && (
          <div style={styles.negotiationWrap}>
            {/* Mobile stats strip */}
            <div className="mobile-stats-strip">
              <div className="stat-chip">
                <div className="stat-chip-val" style={{ color: store.meetingStats.positionStrength >= 60 ? theme.accent.green : theme.accent.amber }}>
                  <PopNumber value={`${store.meetingStats.positionStrength}%`} />
                </div>
                <div className="stat-chip-lbl">Позиция</div>
              </div>
              <div className="stat-chip">
                <div className="stat-chip-val" style={{ color: theme.accent.green }}>
                  <PopNumber value={store.meetingStats.suggestionsUsed} />
                </div>
                <div className="stat-chip-lbl">Принято</div>
              </div>
              <div className="stat-chip">
                <div className="stat-chip-val" style={{ color: store.meetingStats.activeObjections > 0 ? theme.accent.red : theme.text.primary }}>
                  <PopNumber value={store.meetingStats.activeObjections} />
                </div>
                <div className="stat-chip-lbl">Возраж.</div>
              </div>
            </div>

            <div className="meeting-layout" style={styles.meetingLayout}>
              {/* Left: suggestions (wide) */}
              <div style={styles.leftPanel}>
                <SuggestionPanel />
              </div>
              {/* Right: transcript (bottom sheet on mobile) */}
              {drawerOpen && <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} />}
              <div className={`meeting-right-panel${drawerOpen ? ' drawer-open' : ''}`} style={styles.rightPanel}>
                <div className="sheet-handle-row">
                  <div style={{ width: 24 }} />
                  <div className="sheet-title">
                    <span className="sheet-dot" />
                    Транскрипция
                  </div>
                  <button className="sheet-close" onClick={() => setDrawerOpen(false)}>&times;</button>
                </div>
                <ChatDisplay onSetSpeakerRole={(name, side) => sendJSON({ type: 'set_speaker_role', name, side } as any)} />
                <MeetingStats onSaveToHistory={() => sendJSON({ type: 'save_to_history' })} />
              </div>
              {/* Third column: дерево общения (скрывается на узких экранах через CSS) */}
              <div className="meeting-tree-panel" style={styles.treePanel}>
                <ConversationTreePanel meetingId={store.currentMeetingId} />
              </div>
            </div>
          </div>
        )}

        {/* Контекст встречи */}
        {activeTab === 1 && (
          <div className="mobile-content-pad" style={styles.contextPanel}>
            {/* Этап 2: статус live-комнаты */}
            {store.currentMeetingId != null && (
              <div style={styles.roomStatus}>
                <span style={styles.roomStatusItem}>Meeting ID: <b style={{ color: theme.text.primary }}>{store.currentMeetingId}</b></span>
                <span style={styles.roomStatusItem}>
                  <span style={{ ...styles.roomDot, background: store.roomConnected ? theme.accent.green : theme.text.muted }} />
                  {store.roomConnected ? 'Room connected' : 'Room offline'}
                </span>
                <span style={styles.roomStatusItem}>
                  Active audio: <b style={{ color: store.recording ? theme.accent.green : theme.text.muted }}>
                    {store.recording ? (store.deviceRole || 'устройство') : 'none'}
                  </b>
                </span>
              </div>
            )}

            {/* Этап 3: Телефон как диктофон */}
            {store.currentMeetingId != null && (
              <div style={styles.contextCard}>
                <div style={styles.sectionHeader}>
                  <span style={styles.dot} />
                  <span style={styles.sectionTitle}>Телефон как диктофон</span>
                </div>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
                  <div style={{ background: '#0D1018', padding: 8, borderRadius: 8, border: `1px solid ${theme.border.default}`, lineHeight: 0 }}>
                    <QRCodeSVG
                      value={`${window.location.origin}/recorder/${store.currentMeetingId}`}
                      size={120}
                      bgColor="#0D1018"
                      fgColor="#EDF2FF"
                    />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 200 }}>
                    <div style={{ fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, wordBreak: 'break-all' }}>
                      {`${window.location.origin}/recorder/${store.currentMeetingId}`}
                    </div>
                    <button
                      style={styles.copyBtn}
                      onClick={() => {
                        const url = `${window.location.origin}/recorder/${store.currentMeetingId}`;
                        navigator.clipboard?.writeText(url)
                          .then(() => showToast('Ссылка скопирована', 'success'))
                          .catch(() => showToast('Не удалось скопировать', 'error'));
                      }}
                    >
                      Скопировать ссылку
                    </button>
                    <span style={{ fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted }}>
                      отсканируйте QR телефоном (после входа) — откроется диктофон
                    </span>
                  </div>
                </div>
                <div style={styles.phoneStatus}>
                  <span><Dot2 on={!!liveState?.desktop_connected} /> desktop</span>
                  <span><Dot2 on={!!liveState?.phone_connected} /> phone</span>
                  <span><Dot2 on={!!liveState?.phone_recording} color={theme.accent.red} /> phone recording</span>
                  <span style={{ color: theme.text.muted }}>
                    источник: {liveState?.active_audio_source ? (liveState?.phone_recording ? 'телефон' : 'desktop') : 'нет'}
                  </span>
                </div>
              </div>
            )}

            {/* Название встречи */}
            <div style={styles.contextCard}>
              <div style={styles.sectionHeader}>
                <span style={styles.dot} />
                <span style={styles.sectionTitle}>Название встречи</span>
              </div>
              <input
                type="text"
                placeholder="Например: Переговоры с заказчиком ЖК Рассвет"
                value={store.meetingName}
                onChange={(e) => handleMeetingNameChange(e.target.value)}
                style={styles.contextInput}
              />
            </div>

            {/* Документы встречи (Этап 4: S3 + извлечение текста + контекст LLM) */}
            <MeetingDocuments
              meetingId={store.currentMeetingId}
              customerId={store.selectedCustomerId}
              objectId={store.selectedObjectId}
            />

            {/* Контекст */}
            <MeetingContext onContextChange={handleContextChange} />

            {/* Сохранить встречу / Новая встреча */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button
                className="save-meeting-btn"
                onClick={handleSaveMeeting}
                disabled={savingMeeting}
                style={{
                  ...styles.saveMeetingBtn,
                  opacity: savingMeeting ? 0.6 : 1,
                  cursor: savingMeeting ? 'wait' : 'pointer',
                }}
              >
                {savingMeeting ? 'Сохранение...' : 'Сохранить встречу'}
              </button>
              <button
                onClick={() => { startSession(true); showToast('Новая встреча', 'success'); }}
                style={styles.newMeetingBtn}
              >
                + Новая встреча
              </button>
            </div>

            {/* Этап 5: итоги встречи / протокол */}
            <FinalizationPanel meetingId={store.currentMeetingId} />
          </div>
        )}

        {/* Настройки */}
        {activeTab === 2 && settings && (
          <div className="settings-layout mobile-content-pad" style={styles.settingsLayout}>
            <nav style={styles.settingsNav}>
              {SETTINGS_SECTIONS.map((sec) => (
                <button
                  key={sec.id}
                  onClick={() => setSettingsSection(sec.id)}
                  style={settingsSection === sec.id ? styles.navActive : styles.navItem}
                >
                  <span style={{ fontSize: 14 }}>{sec.icon}</span> {sec.label}
                </button>
              ))}
            </nav>
            <div style={styles.settingsContent}>
              {settingsSection === 'stt' && (
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
              {settingsSection === 'llm' && (
                <LLMSettings
                  model={settings.llm_model}
                  temperature={settings.temperature}
                  onModelChange={(m) => setSettings({ ...settings, llm_model: m })}
                  onTemperatureChange={(t) => setSettings({ ...settings, temperature: t })}
                  activeServices={activeServices}
                />
              )}
              {settingsSection === 'hints' && (
                <HintsSettings
                  suggestionTypes={settings.custom_suggestion_types || DEFAULT_SUGGESTION_TYPES}
                  triggerKeywords={settings.custom_trigger_keywords || DEFAULT_TRIGGER_KEYWORDS}
                  onSuggestionTypesChange={(types) => setSettings({ ...settings, custom_suggestion_types: types })}
                  onTriggerKeywordsChange={(keywords) => setSettings({ ...settings, custom_trigger_keywords: keywords })}
                />
              )}
              {settingsSection === 'roles' && (
                <RolesTab onRoleSelect={handleRoleSelect} />
              )}
              {settingsSection === 'storage' && (
                <StorageSettings
                  localPath={settings.local_storage_path || ''}
                  onChange={(path) => setSettings({ ...settings, local_storage_path: path })}
                />
              )}
              {settingsSection === 'notifications' && (
                <PlaceholderSection title="Уведомления" text="Звуковые уведомления, push-нотификации, уровни важности. Раздел в разработке." />
              )}
              {settingsSection === 'locale' && (
                <PlaceholderSection title="Язык и регион" text="Язык интерфейса, формат даты и валюты. Раздел в разработке." />
              )}
              <button
                onClick={handleApplySettings}
                disabled={applyingSettings}
                style={{
                  ...styles.applyBtn,
                  opacity: applyingSettings ? 0.6 : 1,
                  cursor: applyingSettings ? 'wait' : 'pointer',
                }}
              >
                {applyingSettings ? 'Сохранение...' : 'Применить настройки'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Drawer toggle (mobile only) */}
      {activeTab === 0 && (
        <div className="drawer-toggle" onClick={() => setDrawerOpen(true)}>
          <div className="drawer-handle" />
          <span className="drawer-label">Транскрипция</span>
        </div>
      )}

      {/* Bottom bar — edge-to-edge, outside padded content */}
      {activeTab === 0 && (
        <ControlButtons
          onStartListening={handleStartListening}
          onStopListening={handleStopListening}
          onRequestSuggestion={() => sendJSON({ type: 'request_suggestion' })}
          onStrengthenPosition={() => sendJSON({ type: 'strengthen_position' })}
          modelName={settings?.llm_model}
        />
      )}

      {/* Toast notification */}
      {toast && (
        <div
          key={toast.message + Date.now()}
          style={{
            ...styles.toast,
            borderColor: toast.type === 'success' ? theme.accent.green : theme.accent.red,
            background: toast.type === 'success'
              ? 'rgba(46,229,157,0.12)'
              : 'rgba(255,75,110,0.12)',
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

      {/* Mobile bottom nav */}
      <nav className={`mobile-nav${drawerOpen ? ' nav-hidden' : ''}`}>
        {(['Сессия', 'Контекст', 'Настройки'] as const).map((label, i) => (
          <button
            key={label}
            className={`mobile-nav-item${activeTab === i ? ' active' : ''}`}
            onClick={() => setActiveTab(i)}
          >
            <span className="nav-ico">{['◎', '📄', '⚙'][i]}</span>
            <span className="nav-lbl">{label}</span>
            {activeTab === i && <span className="nav-dot" />}
          </button>
        ))}
      </nav>
    </div>
  );
}

function Dot2({ on, color }: { on: boolean; color?: string }) {
  return (
    <span style={{
      width: 7, height: 7, borderRadius: '50%', display: 'inline-block', marginRight: 5,
      background: on ? (color || theme.accent.green) : theme.text.muted, flexShrink: 0,
    }} />
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
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' },
  tabs: {
    display: 'flex', gap: 0,
    borderBottom: `1px solid ${theme.border.default}`,
    padding: '0 24px', background: theme.bg.secondary, flexShrink: 0,
  },
  tab: {
    padding: '10px 16px', background: 'transparent', border: 'none',
    cursor: 'pointer', fontSize: 12, fontWeight: 500,
    fontFamily: theme.font.body, letterSpacing: '0.02em', transition: 'color 0.2s',
  },
  content: { flex: 1, overflow: 'auto', padding: 20 },
  contentNegotiations: { flex: 1, overflow: 'hidden', padding: '16px 20px 0' },

  /* Переговоры */
  negotiationWrap: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 },
  meetingLayout: { display: 'flex', gap: 16, flex: 1, minHeight: 0 },
  leftPanel: { flex: 3, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 },
  rightPanel: { width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 0 },
  treePanel: { width: 340, flexShrink: 0, display: 'flex', flexDirection: 'column', minHeight: 0 },

  /* Контекст встречи */
  contextPanel: { display: 'flex', flexDirection: 'column', gap: 20 },
  roomStatus: {
    display: 'flex', gap: 18, flexWrap: 'wrap' as const, alignItems: 'center',
    padding: '8px 14px', background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`, borderRadius: 8,
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary,
  },
  roomStatusItem: { display: 'flex', alignItems: 'center', gap: 6, letterSpacing: '0.04em' },
  roomDot: { width: 7, height: 7, borderRadius: '50%', flexShrink: 0 },
  copyBtn: {
    padding: '8px 14px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 11,
    fontFamily: theme.font.mono, fontWeight: 500,
  },
  phoneStatus: {
    display: 'flex', gap: 14, flexWrap: 'wrap' as const, alignItems: 'center',
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, marginTop: 2,
  },
  newMeetingBtn: {
    padding: '12px 22px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 13,
    fontWeight: 600, fontFamily: theme.font.body, alignSelf: 'flex-start', letterSpacing: '0.02em',
  },
  contextInput: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box' as const,
  },
  saveMeetingBtn: {
    padding: '12px 28px',
    background: theme.accent.amber,
    border: 'none',
    borderRadius: 8,
    color: '#080A0F',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
    fontFamily: theme.font.body,
    alignSelf: 'flex-start',
    transition: 'opacity 0.2s',
    letterSpacing: '0.02em',
  },
  contextCard: {
    background: theme.bg.card, border: `1px solid ${theme.border.default}`,
    borderRadius: 12, padding: 20,
    display: 'flex', flexDirection: 'column', gap: 14,
  },

  /* Shared section header */
  sectionHeader: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  sectionTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const,
    color: theme.text.primary, flex: 1,
  },
  sectionMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },

  /* Настройки */
  settingsLayout: { display: 'flex', gap: 24 },
  settingsNav: {
    display: 'flex', flexDirection: 'column', gap: 4, minWidth: 220, flexShrink: 0,
  },
  navActive: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '10px 16px', background: theme.accent.amber, color: '#080A0F',
    border: 'none', borderRadius: 8, fontSize: 12, fontWeight: 600,
    fontFamily: theme.font.body, cursor: 'pointer', textAlign: 'left' as const,
  },
  navItem: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '10px 16px', background: 'transparent', color: theme.text.secondary,
    border: 'none', borderRadius: 8, fontSize: 12,
    fontFamily: theme.font.body, cursor: 'pointer', textAlign: 'left' as const,
  },
  settingsContent: { flex: 1, display: 'flex', flexDirection: 'column', gap: 20 },
  placeholderCard: {
    background: theme.bg.card, border: `1px solid ${theme.border.default}`,
    borderRadius: 12, padding: 24,
    display: 'flex', flexDirection: 'column', gap: 12,
  },
  placeholderText: {
    color: theme.text.muted, fontSize: 13, fontFamily: theme.font.body, lineHeight: 1.6,
  },
  applyBtn: {
    marginTop: 8, padding: '9px 22px', background: theme.accent.amber,
    border: 'none', borderRadius: 7, color: '#080A0F', cursor: 'pointer',
    fontSize: 12, fontWeight: 600, fontFamily: theme.font.body, alignSelf: 'flex-start',
    transition: 'opacity 0.2s',
  },
  toast: {
    position: 'fixed' as const, bottom: 24, right: 24, zIndex: 9999,
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '10px 18px', borderRadius: 8,
    border: '1px solid',
    backdropFilter: 'blur(12px)',
    animation: 'toastSlideIn 0.3s ease-out',
  },
};
