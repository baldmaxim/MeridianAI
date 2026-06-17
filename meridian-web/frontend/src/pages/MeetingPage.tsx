import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useMeetingStore } from '../store/meetingStore';
import { getSettings } from '../api/settings';
import { createMeeting } from '../api/meetings';
import { getMeetingDetail } from '../api/history';
import { ChatDisplay } from '../components/meeting/ChatDisplay';
import { SuggestionPanel } from '../components/meeting/SuggestionPanel';
import { ControlButtons } from '../components/meeting/ControlButtons';
import { MeetingStats } from '../components/meeting/MeetingStats';
import { ConversationTreePanel } from '../components/meeting/ConversationTreePanel';
import { DictaphoneView } from '../components/meeting/DictaphoneView';
import { ModeSwitch } from '../components/meeting/ModeSwitch';
import { getConversationTree } from '../api/conversationTree';
import { PopNumber } from '../components/common/PopNumber';
import { CollapsibleSection } from '../components/common/CollapsibleSection';
import { ContextBasket } from '../components/context/ContextBasket';
import { FinalizationPanel } from '../components/protocol/FinalizationPanel';
import { MeetingContext } from '../components/context/MeetingContext';
import { MeetingAISettingsBlock } from '../components/context/MeetingAISettings';
import { RolesTab } from '../components/context/RolesTab';
import { theme } from '../styles/theme';
import { paths } from '../lib/navigation';
import type { UserSettings } from '../types';

const TABS = ['Переговоры', 'Контекст встречи'] as const;

interface Props {
  meetingId?: number;
  onBack: () => void;
}

export function MeetingPage({ meetingId, onBack }: Props) {
  const [activeTab, setActiveTab] = useState(0);
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const ctxSendTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const [level, setLevel] = useState(0);
  const { connect, disconnect, sendJSON, sendBinary } = useWebSocket();
  const { start: startAudio, stop: stopAudio } = useAudioRecorder(sendBinary, setLevel);
  const store = useMeetingStore();

  // Встреча (строка в БД) создаётся ТОЛЬКО вручную: старт записи / «Новая встреча» /
  // выбор заказчика. Открытие или reload портала НИЧЕГО не создаёт.
  // startSession: вернуть существующий draft либо создать новый, затем подключиться.
  // forceNew=true — начать НОВУЮ встречу без reload.
  const startSession = useCallback(async (forceNew = false): Promise<number | null> => {
    if (forceNew) {
      disconnect();
      useMeetingStore.getState().newMeetingSession();
    }
    const st = useMeetingStore.getState();
    let id = st.currentMeetingId ?? st.draftMeetingId ?? st.meetingSavedId ?? null;
    const alreadyConnected = id != null && st.isConnected && !forceNew;
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
        useMeetingStore.getState().setDraftMeetingId(m.id);
      } catch {
        return null;
      }
    }
    useMeetingStore.getState().setCurrentMeetingId(id);
    // connect всегда с конкретным meetingId — bare /ws/meeting не используем.
    if (!alreadyConnected) connect({ meetingId: id, deviceRole: 'desktop' });
    return id;
  }, [connect, disconnect]);

  // Дождаться открытия WS, чтобы отправить start_audio сразу после создания встречи.
  const waitForConnected = useCallback((timeoutMs = 5000): Promise<boolean> => {
    return new Promise((resolve) => {
      if (useMeetingStore.getState().isConnected) { resolve(true); return; }
      const start = Date.now();
      const iv = setInterval(() => {
        if (useMeetingStore.getState().isConnected) { clearInterval(iv); resolve(true); }
        else if (Date.now() - start > timeoutMs) { clearInterval(iv); resolve(false); }
      }, 100);
    });
  }, []);

  useEffect(() => {
    // НЕ создаём встречу при заходе. Подключаемся к встрече из URL (meetingId)
    // или к уже выбранной в сторе (draft / текущая).
    const st = useMeetingStore.getState();
    const existing = meetingId ?? st.currentMeetingId ?? st.draftMeetingId ?? null;
    if (existing != null) {
      st.setCurrentMeetingId(existing);
      connect({ meetingId: existing, deviceRole: 'desktop' });
      // По прямой ссылке стор пуст — подтянуть заказчика/объект встречи (WS их не шлёт).
      getMeetingDetail(existing).then((d) => {
        const s2 = useMeetingStore.getState();
        s2.setDraftMeetingId(existing);
        s2.setSelectedCustomerId(d.customer_id);
        s2.setSelectedObjectId(d.object_id);
        s2.setSelectedCustomerName(d.customer_name);
        s2.setSelectedObjectName(d.object_name);
      }).catch(() => {});
    }
    getSettings().then((s) => {
      setSettings(s);
      store.setCustomSuggestionTypes(s.custom_suggestion_types);
    }).catch(() => {});
    return () => { disconnect(); if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Conversation Tree: начальная загрузка дерева при открытии встречи
  useEffect(() => {
    if (store.currentMeetingId == null) return;
    getConversationTree(store.currentMeetingId)
      .then((tree) => store.setConversationTree(tree.topics, tree.tree_version, tree.unassigned_speakers))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.currentMeetingId]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (store.isListening || store.messages.length > 0) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [store.isListening, store.messages.length]);

  const handleStartListening = useCallback(async () => {
    // Этап 3: если активный источник аудио — другое устройство (телефон), не стартуем
    let st = useMeetingStore.getState();
    if (st.activeAudioSource && st.activeAudioSource !== st.connectionId) {
      store.setError('Источник аудио занят (идёт запись с телефона)');
      return;
    }
    // Встреча создаётся вручную при первом старте записи (не при заходе на портал).
    if (st.currentMeetingId == null || !st.isConnected) {
      const id = await startSession(false);
      if (id == null) { store.setError('Не удалось создать встречу'); return; }
      const ok = await waitForConnected();
      if (!ok) { store.setError('Не удалось подключиться к встрече'); return; }
      st = useMeetingStore.getState();
      if (st.activeAudioSource && st.activeAudioSource !== st.connectionId) {
        store.setError('Источник аудио занят (идёт запись с телефона)');
        return;
      }
    }
    try {
      await startAudio();
      sendJSON({ type: 'start_audio' });
      store.setListening(true);
    } catch {
      store.setError('Не удалось получить доступ к микрофону');
    }
  }, [startAudio, sendJSON, startSession, waitForConnected, store]);

  const handleStopListening = useCallback(() => {
    stopAudio();
    sendJSON({ type: 'stop_audio' });
    store.setListening(false);
  }, [stopAudio, sendJSON, store]);

  // Hotkeys: Space — toggle listening, H — suggestion, S — strengthen
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (e.code === 'Space') {
        e.preventDefault();
        if (store.isListening) {
          handleStopListening();
        } else {
          handleStartListening();
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
  }, [store.isListening, store.isConnected, store.suggestionLoading, store.strengthenLoading, handleStartListening, handleStopListening, sendJSON]);

  // Дебаунс отправки контекста: локальный стор обновляется мгновенно (поле/шапка
  // реагируют сразу), а update_meeting_context уходит на сервер с задержкой —
  // вместе с guard contextEditedAt это гасит self-echo (символы не пропадают).
  // Единый отправитель контекста: читает ВСЕ поля из стора в момент отправки.
  // Поля раскиданы по разным карточкам — кортеж собрать неоткуда, поэтому источник
  // истины один (стор). markContextEdited + debounce 350ms гасят self-echo.
  const pushContext = useCallback(() => {
    useMeetingStore.getState().markContextEdited();
    if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current);
    ctxSendTimer.current = setTimeout(() => {
      const st = useMeetingStore.getState();
      sendJSON({ type: 'update_meeting_context', title: st.meetingName || undefined, topic: st.meetingTopic, notes: st.meetingNotes, negotiation_type: st.negotiationType, meeting_role: st.meetingRole, opponent_weaknesses: st.opponentWeaknesses });
    }, 350);
  }, [sendJSON]);

  const handleTopicChange = useCallback((v: string) => { useMeetingStore.getState().setMeetingTopic(v); pushContext(); }, [pushContext]);
  const handleWeaknessesChange = useCallback((v: string) => { useMeetingStore.getState().setOpponentWeaknesses(v); pushContext(); }, [pushContext]);

  const handleMeetingNameChange = useCallback((name: string) => {
    const s = useMeetingStore.getState();
    s.setMeetingName(name);
    s.markContextEdited();
    if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current);
    ctxSendTimer.current = setTimeout(() => {
      const st = useMeetingStore.getState();
      sendJSON({ type: 'update_meeting_context', title: name, topic: st.meetingTopic, notes: st.meetingNotes, negotiation_type: st.negotiationType, meeting_role: st.meetingRole, opponent_weaknesses: st.opponentWeaknesses });
    }, 350);
  }, [sendJSON]);

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

  const copyMeetingLink = useCallback(() => {
    const id = useMeetingStore.getState().currentMeetingId;
    if (id == null) return;
    const url = window.location.origin + paths.meetingRoom(id);
    const done = () => showToast('Ссылка скопирована', 'success');
    const fail = () => showToast('Не удалось скопировать ссылку', 'error');
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done, fail);
    else fail();
  }, [showToast]);

  // Верхняя панель встречи: «назад» + переключатель вида (диктофон/полный) + ссылка.
  // Общая для обоих режимов — переключатель доступен и в диктофоне, и в полном.
  const topBar = (
    <div style={styles.topBar}>
      <style>{`
        @media (max-width: 767px) {
          .mp-ref-label { display: none !important; }
          .mp-ref { gap: 10px !important; }
        }
      `}</style>
      <button onClick={onBack} style={styles.backBtn} aria-label="Назад" title="В главное меню">
        <span>←</span><span className="mp-btn-label"> Назад</span>
      </button>
      {/* Заказчик/объект — справочно, read-only (привязка задаётся при создании встречи) */}
      {(store.selectedCustomerName || store.selectedObjectName) && (
        <div className="mp-ref" style={styles.refInfo}>
          {store.selectedCustomerName && (
            <span style={styles.refItem} title={`Заказчик: ${store.selectedCustomerName}`}>
              <span className="mp-ref-label" style={styles.refLabel}>Заказчик</span>
              <span style={styles.refVal}>{store.selectedCustomerName}</span>
            </span>
          )}
          {store.selectedObjectName && (
            <span style={styles.refItem} title={`Объект: ${store.selectedObjectName}`}>
              <span className="mp-ref-label" style={styles.refLabel}>Объект</span>
              <span style={styles.refVal}>{store.selectedObjectName}</span>
            </span>
          )}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <ModeSwitch />
        {store.currentMeetingId != null && (
          <button onClick={copyMeetingLink} style={styles.linkBtn} aria-label="Скопировать ссылку" title="Скопировать ссылку на встречу">
            <span>🔗</span><span className="mp-btn-label"> Ссылка</span>
          </button>
        )}
      </div>
    </div>
  );

  const toastEl = toast && (
    <div
      key={toast.message + Date.now()}
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
  );

  // Простой режим (вид «Пользователь») — чистый диктофон поверх той же сессии.
  // Переключение режима — единым слайдером роли «Админ ⟷ Пользователь» в шапке.
  if (store.uiMode === 'simple') {
    return (
      <div style={styles.container}>
        {topBar}
        <DictaphoneView
          level={level}
          isListening={store.isListening}
          isConnected={store.isConnected}
          onStart={handleStartListening}
          onStop={handleStopListening}
        />
        {toastEl}
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {topBar}
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
        {activeTab === 1 && (() => {
          const ctxMeetingId = store.currentMeetingId ?? store.draftMeetingId ?? null;
          return (
          <div className="mobile-content-pad" style={styles.contextPanel}>
            {/* A. Компактная карточка «Встреча» */}
            <div style={styles.contextCard}>
              <div style={styles.sectionHeader}>
                <span style={styles.dot} />
                <span style={styles.sectionTitle}>Встреча</span>
                {store.currentMeetingId != null && (
                  <span style={styles.roomBadge}>
                    <span style={{ ...styles.roomDot, background: store.roomConnected ? theme.accent.green : theme.text.muted }} />
                    {store.roomConnected ? (store.recording ? 'REC' : 'online') : 'offline'}
                  </span>
                )}
              </div>

              <div className="context-columns" style={styles.meetingGrid}>
                <div style={styles.meetingField}>
                  <label style={styles.miniLabel}>Название встречи</label>
                  <input
                    type="text"
                    placeholder="Например: Переговоры с заказчиком ЖК Рассвет"
                    value={store.meetingName}
                    onChange={(e) => handleMeetingNameChange(e.target.value)}
                    style={styles.contextInput}
                  />
                </div>
                <div style={styles.meetingField}>
                  <label style={styles.miniLabel}>Тема / цель встречи</label>
                  <input
                    type="text"
                    placeholder="Финальные условия контракта — ЖК Рассвет"
                    value={store.meetingTopic}
                    onChange={(e) => handleTopicChange(e.target.value)}
                    style={styles.contextInput}
                  />
                </div>
              </div>

              {(store.selectedCustomerName || store.selectedObjectName) && (
                <div style={styles.refRow}>
                  {store.selectedCustomerName && (
                    <span style={styles.refChip}><span style={styles.refChipLabel}>Заказчик</span>{store.selectedCustomerName}</span>
                  )}
                  {store.selectedObjectName && (
                    <span style={styles.refChip}><span style={styles.refChipLabel}>Объект</span>{store.selectedObjectName}</span>
                  )}
                </div>
              )}

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
            </div>

            {/* B. Корзина контекста — «что попадёт в подсказки» */}
            <ContextBasket
              meetingId={ctxMeetingId}
              customerId={store.selectedCustomerId}
              objectId={store.selectedObjectId}
            />

            {/* C. Краткие настройки */}
            <CollapsibleSection title="Краткие настройки" defaultOpen>
              <MeetingContext pushContext={pushContext} />
            </CollapsibleSection>

            {/* D. Расширенные настройки */}
            <CollapsibleSection title="Расширенные настройки">
              {/* AI-настройки встречи */}
              {ctxMeetingId != null && <MeetingAISettingsBlock meetingId={ctxMeetingId} />}

              {/* Слабые стороны оппонента */}
              <CollapsibleSection title="Слабые стороны оппонента">
                <textarea
                  placeholder={"Известные проблемы, сорванные сроки, рыночная позиция..."}
                  value={store.opponentWeaknesses}
                  onChange={(e) => handleWeaknessesChange(e.target.value)}
                  rows={3}
                  style={styles.weakTextarea}
                />
              </CollapsibleSection>

              {/* Активная роль (live, через WS change_role) */}
              <div style={styles.contextCard}>
                <div style={styles.sectionHeader}>
                  <span style={styles.dot} />
                  <span style={styles.sectionTitle}>Активная роль (для подсказок)</span>
                </div>
                <RolesTab onRoleSelect={handleRoleSelect} />
              </div>

              {/* Сохранить встречу */}
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
              </div>

              {/* Этап 5: итоги встречи / протокол */}
              <FinalizationPanel meetingId={store.currentMeetingId} />
            </CollapsibleSection>
          </div>
          );
        })()}
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
      {toastEl}

      {/* Mobile bottom nav */}
      <nav className={`mobile-nav${drawerOpen ? ' nav-hidden' : ''}`}>
        {(['Сессия', 'Контекст'] as const).map((label, i) => (
          <button
            key={label}
            className={`mobile-nav-item${activeTab === i ? ' active' : ''}`}
            onClick={() => setActiveTab(i)}
          >
            <span className="nav-ico">{['◎', '📄'][i]}</span>
            <span className="nav-lbl">{label}</span>
            {activeTab === i && <span className="nav-dot" />}
          </button>
        ))}
      </nav>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' },
  topBar: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    padding: '8px 20px', background: theme.bg.secondary,
    borderBottom: `1px solid ${theme.border.default}`, flexShrink: 0,
  },
  backBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px',
    background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em', flexShrink: 0,
  },
  refInfo: {
    display: 'flex', alignItems: 'center', gap: 18, flex: 1, minWidth: 0,
    overflow: 'hidden', paddingLeft: 4,
  },
  refItem: {
    display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0,
  },
  refLabel: {
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.1em',
    textTransform: 'uppercase' as const, color: theme.text.muted, flexShrink: 0,
  },
  refVal: {
    fontFamily: theme.font.body, fontSize: 13, fontWeight: 600, color: theme.text.primary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  linkBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px',
    background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em',
  },
  tabs: {
    display: 'flex', gap: 0, alignItems: 'center',
    borderBottom: `1px solid ${theme.border.default}`,
    padding: '0 24px', background: theme.bg.secondary, flexShrink: 0,
  },
  simpleBar: {
    display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
    padding: '8px 16px', borderBottom: `1px solid ${theme.border.default}`,
    background: theme.bg.secondary, flexShrink: 0,
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
  roomBadge: {
    display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
    padding: '3px 10px', borderRadius: 20, background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`, fontFamily: theme.font.mono,
    fontSize: 10, letterSpacing: '0.06em', color: theme.text.secondary,
    textTransform: 'uppercase' as const,
  },
  meetingGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
  meetingField: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 },
  miniLabel: {
    fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber,
    letterSpacing: '0.08em', textTransform: 'uppercase' as const,
  },
  refRow: { display: 'flex', gap: 10, flexWrap: 'wrap' as const },
  refChip: {
    display: 'inline-flex', alignItems: 'baseline', gap: 8,
    padding: '6px 12px', borderRadius: 8, background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`, fontFamily: theme.font.body,
    fontSize: 13, fontWeight: 600, color: theme.text.primary, minWidth: 0,
  },
  refChipLabel: {
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.1em',
    textTransform: 'uppercase' as const, color: theme.text.muted,
  },
  weakTextarea: {
    padding: '10px 14px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body,
    outline: 'none', resize: 'vertical' as const, width: '100%', boxSizing: 'border-box' as const,
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
  toast: {
    position: 'fixed' as const, bottom: 24, right: 24, zIndex: 9999,
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '10px 18px', borderRadius: 8,
    border: '1px solid',
    backdropFilter: 'blur(12px)',
    animation: 'toastSlideIn 0.3s ease-out',
  },
};
