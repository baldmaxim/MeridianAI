import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useMeetingStore } from '../store/meetingStore';
import { getSettings } from '../api/settings';
import { createMeeting } from '../api/meetings';
import { getMeetingDetail } from '../api/history';
import { ChatDisplay } from '../components/meeting/ChatDisplay';
import { SpeakerSideAssignmentPanel } from '../components/meeting/SpeakerSideAssignmentPanel';
import { ObserverPanel } from '../components/meeting/ObserverPanel';
import { SecondaryShadowPanel } from '../components/meeting/SecondaryShadowPanel';
import { IngestPanel } from '../components/meeting/IngestPanel';
import { MultiChannelLivePanel } from '../components/meeting/MultiChannelLivePanel';
import { MultiChannelReconciliationPanel } from '../components/meeting/MultiChannelReconciliationPanel';
import { ProductionCutoverPanel } from '../components/meeting/ProductionCutoverPanel';
import { SuggestionPanel } from '../components/meeting/SuggestionPanel';
import { ControlButtons } from '../components/meeting/ControlButtons';
import { MeetingStats } from '../components/meeting/MeetingStats';
import { ConversationTreePanel } from '../components/meeting/ConversationTreePanel';
import { DictaphoneView } from '../components/meeting/DictaphoneView';
import { ModeSwitch } from '../components/meeting/ModeSwitch';
import { getConversationTree } from '../api/conversationTree';
import { PopNumber } from '../components/common/PopNumber';
import { IconSwap } from '../components/common/IconSwap';
import { useExitTransition } from '../hooks/useExitTransition';
import { CollapsibleSection } from '../components/common/CollapsibleSection';
import { ContextBasket } from '../components/context/ContextBasket';
import { ragContextApiAdapter } from '../api/ragContextAdapter';
import { FinalizationPanel } from '../components/protocol/FinalizationPanel';
import { MeetingContext } from '../components/context/MeetingContext';
import { MeetingAISettingsBlock } from '../components/context/MeetingAISettings';
import { RolesTab } from '../components/context/RolesTab';
import { getSpeakerRoles, putSpeakerRole } from '../api/speakerRoles';
import { listSpeakerCorrections, putSpeakerCorrection, deleteSpeakerCorrection } from '../api/speakerCorrections';
import { toPublicSpeakerSide, nextPublicSpeakerSide, type PublicSpeakerSide } from '../lib/speakerSides';
import { segmentOverrideSide } from '../lib/segmentCorrections';
import type { SpeakerSegmentCorrection } from '../types';
import { theme } from '../styles/theme';
import { paths } from '../lib/navigation';
import type { UserSettings } from '../types';

const TABS = ['Переговоры', 'Контекст встречи'] as const;

// Дата в формате ДД.ММ.ГГГГ.
function formatDmy(d: Date): string {
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
}

// Дефолтное название встречи: «Заказчик_Объект_ДД.ММ.ГГГГ» (непустые части через «_»).
function buildDefaultMeetingName(customerName: string | null, objectName: string | null): string {
  return [customerName, objectName, formatDmy(new Date())].filter((p) => p && p.trim()).join('_');
}

// Дата начала записи встречи для показа в шапке (ISO → ДД.ММ.ГГГГ).
function formatMeetingDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : formatDmy(d);
}

interface Props {
  meetingId?: number;
  onBack: () => void;
}

export function MeetingPage({ meetingId, onBack }: Props) {
  const [activeTab, setActiveTab] = useState(0);
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const ctxSendTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

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
          title: st.meetingName || buildDefaultMeetingName(st.selectedCustomerName, st.selectedObjectName) || null,
          meeting_topic: st.meetingTopic || null,
          meeting_notes: st.meetingNotes || null,
          negotiation_type: st.negotiationType || null,
          meeting_role: st.meetingRole || null,
          opponent_weaknesses: st.opponentWeaknesses || null,
        });
        id = m.id;
        useMeetingStore.getState().setDraftMeetingId(m.id);
        useMeetingStore.getState().setMeetingStartedAt(m.started_at);
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
        s2.setMeetingStartedAt(d.started_at ?? null);
        // Тема/цель — read-only, генерируется LLM; название — пользовательское.
        s2.setMeetingTopic(d.meeting_topic ?? '');
        if (d.title) s2.setMeetingName(d.title);
      }).catch(() => {});
    }
    getSettings().then((s) => {
      setSettings(s);
      store.setCustomSuggestionTypes(s.custom_suggestion_types);
    }).catch(() => {});
    return () => {
      disconnect();
      if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current);
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Этап 7: подтянуть persisted-стороны спикеров при открытии встречи (до live broadcast)
  useEffect(() => {
    const mid = store.currentMeetingId;
    if (mid == null) return;
    getSpeakerRoles(mid)
      .then((rows) => {
        const map: Record<string, PublicSpeakerSide> = {};
        for (const r of rows) {
          const side = toPublicSpeakerSide(r.side);
          if (side) map[r.speaker_label] = side;
        }
        useMeetingStore.getState().setSpeakerRoles(map);
      })
      .catch(() => {});  // тихо игнорируем — роли подтянутся по WS
    // Этап 8: persisted segment-level коррекции
    listSpeakerCorrections(mid)
      .then((rows) => {
        const map: Record<string, SpeakerSegmentCorrection> = {};
        for (const r of rows) map[r.segment_key] = r;
        useMeetingStore.getState().setSpeakerCorrections(map);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.currentMeetingId]);

  // Этап 8.1: исправить ОДНУ реплику (side и/или corrected_speaker_label). Merge с существующей
  // коррекцией, оптимистично + REST. Пустой результат → delete. Встречу НЕ создаёт.
  const handleSetSegmentCorrection = useCallback(async (
    segmentKey: string,
    originalSpeaker: string,
    patch: { side?: PublicSpeakerSide | ''; correctedSpeakerLabel?: string | null },
  ) => {
    const st = useMeetingStore.getState();
    const mid = st.currentMeetingId;
    if (mid == null || !segmentKey) return;
    const existing = st.speakerCorrections[segmentKey];
    const side: PublicSpeakerSide | '' = patch.side !== undefined
      ? patch.side
      : (toPublicSpeakerSide(existing?.side));
    const correctedLabel: string | null = patch.correctedSpeakerLabel !== undefined
      ? (patch.correctedSpeakerLabel || null)
      : (existing?.corrected_speaker_label ?? null);
    const prev = st.speakerCorrections;
    try {
      if (!side && !correctedLabel) {
        await deleteSpeakerCorrection(mid, segmentKey);
        const map = { ...prev };
        delete map[segmentKey];
        useMeetingStore.getState().setSpeakerCorrections(map);
      } else {
        const rows = await putSpeakerCorrection(mid, segmentKey, {
          side: side || '', corrected_speaker_label: correctedLabel,
          original_speaker_label: originalSpeaker,
        });
        const map: Record<string, SpeakerSegmentCorrection> = {};
        for (const r of rows) map[r.segment_key] = r;
        useMeetingStore.getState().setSpeakerCorrections(map);
      }
    } catch {
      useMeetingStore.getState().setError('Не удалось сохранить исправление реплики');
    }
  }, []);

  // Клик по бейджу реплики циклит сторону, сохраняя corrected_speaker_label.
  const handleCorrectSegment = useCallback((segmentKey: string, originalSpeaker: string) => {
    const current = segmentOverrideSide(useMeetingStore.getState().speakerCorrections, segmentKey);
    handleSetSegmentCorrection(segmentKey, originalSpeaker, { side: nextPublicSpeakerSide(current) });
  }, [handleSetSegmentCorrection]);

  // Единый сеттер стороны спикера: optimistic + WS (или REST fallback). Встречу НЕ создаёт.
  const handleSetSpeakerSide = useCallback(async (name: string, side: PublicSpeakerSide | '' | null) => {
    const label = name.trim();
    if (!label) return;
    const normalized = toPublicSpeakerSide(side);
    const st = useMeetingStore.getState();
    const prev = st.speakerRoles;
    const next: Record<string, string> = { ...prev };
    if (normalized) next[label] = normalized;
    else delete next[label];
    st.setSpeakerRoles(next);

    if (st.isConnected) {
      sendJSON({ type: 'set_speaker_role', name: label, side: normalized || '' });
    } else if (st.currentMeetingId != null) {
      try {
        await putSpeakerRole(st.currentMeetingId, label, { side: normalized || '' });
      } catch {
        useMeetingStore.getState().setSpeakerRoles(prev);  // откат optimistic
        useMeetingStore.getState().setError('Не удалось сохранить сторону спикера');
      }
    }
    // нет соединения и нет встречи → только локальный optimistic (встречу не создаём)
  }, [sendJSON]);

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

  // Дефолт названия встречи «Заказчик_Объект_Дата» — только когда поле пустое и
  // известен заказчик/объект. Не затирает то, что пользователь уже ввёл/подтянуто из БД.
  useEffect(() => {
    if (store.meetingName) return;
    if (!store.selectedCustomerName && !store.selectedObjectName) return;
    useMeetingStore.getState().setMeetingName(
      buildDefaultMeetingName(store.selectedCustomerName, store.selectedObjectName),
    );
  }, [store.meetingName, store.selectedCustomerName, store.selectedObjectName]);

  // После финализации подтянуть сгенерированную тему/название из БД (read-only поле).
  const refreshMeetingMeta = useCallback(() => {
    const id = useMeetingStore.getState().currentMeetingId;
    if (id == null) return;
    getMeetingDetail(id).then((d) => {
      const s2 = useMeetingStore.getState();
      s2.setMeetingTopic(d.meeting_topic ?? '');
      if (d.started_at) s2.setMeetingStartedAt(d.started_at);
      if (d.title) s2.setMeetingName(d.title);
    }).catch(() => {});
  }, []);

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
    const done = () => {
      // Инлайн-фидбек прямо под кнопкой (вместо тоста): чек + всплывающая подпись.
      setLinkCopied(true);
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 2000);
    };
    const fail = () => showToast('Не удалось скопировать ссылку', 'error');
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done, fail);
    else fail();
  }, [showToast]);

  // Дата встречи (начало записи) для шапки.
  const meetingDate = formatMeetingDate(store.meetingStartedAt);
  // Инлайн-уведомление о копировании ссылки (panel-reveal под кнопкой).
  const copyNote = useExitTransition(linkCopied, { closeVar: '--panel-close-dur', fallbackMs: 350 });

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
      <button onClick={onBack} className="t-btn" style={styles.backBtn} aria-label="Назад" title="В главное меню">
        <span>←</span><span className="mp-btn-label"> Назад</span>
      </button>
      {/* Заказчик/объект/дата — справочно, read-only (привязка задаётся при создании встречи) */}
      {(store.selectedCustomerName || store.selectedObjectName || meetingDate) && (
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
          {meetingDate && (
            <span style={styles.refItem} title={`Дата встречи: ${meetingDate}`}>
              <span className="mp-ref-label" style={styles.refLabel}>Дата</span>
              <span style={styles.refVal}>{meetingDate}</span>
            </span>
          )}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <ModeSwitch />
        {store.currentMeetingId != null && (
          <div style={styles.linkWrap}>
            <button onClick={copyMeetingLink} className="t-btn" style={styles.linkBtn} aria-label="Скопировать ссылку" title="Скопировать ссылку на встречу">
              <IconSwap state={linkCopied ? 'b' : 'a'} a="🔗" b="✓" />
              <span className="mp-btn-label"> Ссылка</span>
            </button>
            {copyNote.mounted && (
              <div
                className="t-panel-slide"
                data-open={copyNote.open ? 'true' : 'false'}
                style={{ ...styles.copyNote, ['--panel-translate-y']: '-6px' } as React.CSSProperties}
              >
                Ссылка скопирована
              </div>
            )}
          </div>
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
            className="t-btn"
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
                  <button className="sheet-close t-btn" onClick={() => setDrawerOpen(false)}>&times;</button>
                </div>
                <SpeakerSideAssignmentPanel
                  meetingId={store.currentMeetingId}
                  canEdit={store.canSendAudio}
                  compact
                  onSetSpeakerSide={handleSetSpeakerSide}
                />
                <ChatDisplay
                  onSetSpeakerRole={handleSetSpeakerSide}
                  onCorrectSegment={handleCorrectSegment}
                  onSetSegmentCorrection={handleSetSegmentCorrection}
                />
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
            {/* A. Брифинг встречи: две сбалансированные карточки рядом */}
            <div className="context-columns" style={styles.briefGrid}>
              {/* Встреча — название/тема (стек) + статус */}
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
                    readOnly
                    placeholder="Сформируется автоматически после завершения встречи"
                    value={store.meetingTopic}
                    title="Краткое наименование формируется ИИ после распознавания всех переговоров"
                    style={styles.contextInputReadonly}
                  />
                </div>

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

              {/* Краткие настройки — тип переговоров + ключевые условия */}
              <CollapsibleSection title="Краткие настройки" defaultOpen>
                <MeetingContext pushContext={pushContext} />
              </CollapsibleSection>
            </div>

            {/* B. Источники контекста — на всю ширину */}
            <ContextBasket
              meetingId={ctxMeetingId}
              customerId={store.selectedCustomerId}
              objectId={store.selectedObjectId}
              ensureMeetingId={async () => {
                const st = useMeetingStore.getState();
                if (st.currentMeetingId != null) return st.currentMeetingId;
                return await startSession(false);
              }}
              ragAdapter={ragContextApiAdapter}
            />

            {/* C. Расширенные настройки */}
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
                  className="save-meeting-btn t-btn t-btn-amber"
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

              {/* Этап 9: режим наблюдателя (второй телефон) */}
              <CollapsibleSection title="Наблюдатель (второй телефон)">
                <ObserverPanel meetingId={store.currentMeetingId} />
              </CollapsibleSection>

              {/* Этап 9.2: второй аудиоканал (shadow) */}
              <CollapsibleSection title="Второй аудиоканал (shadow)">
                <SecondaryShadowPanel meetingId={store.currentMeetingId} />
              </CollapsibleSection>

              {/* Этап 9.3: выравнивание источников (multi-source ingest) */}
              <CollapsibleSection title="Синхронизация каналов (ingest)">
                <IngestPanel />
              </CollapsibleSection>

              {/* Этап 9.6: live multi-channel STT (shadow) */}
              <CollapsibleSection title="Live multi-channel STT — shadow">
                <MultiChannelLivePanel meetingId={store.currentMeetingId} sendJSON={sendJSON} />
              </CollapsibleSection>

              {/* Этап 9.7: сопоставление multi-channel candidate с основным transcript */}
              <CollapsibleSection title="Сопоставление с основным transcript">
                <MultiChannelReconciliationPanel meetingId={store.currentMeetingId} sendJSON={sendJSON} />
              </CollapsibleSection>

              {/* Этап 9.8: авторитетный источник транскрипта (production cutover) */}
              <CollapsibleSection title="Источник транскрипта (cutover)">
                <ProductionCutoverPanel meetingId={store.currentMeetingId} sendJSON={sendJSON} />
              </CollapsibleSection>

              {/* Этап 5: итоги встречи / протокол */}
              <FinalizationPanel meetingId={store.currentMeetingId} onFinalized={refreshMeetingMeta} />
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
            className={`mobile-nav-item t-btn${activeTab === i ? ' active' : ''}`}
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
  linkWrap: { position: 'relative', flexShrink: 0 },
  linkBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px',
    background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em',
  },
  copyNote: {
    position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 50,
    display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
    padding: '5px 10px', borderRadius: 6,
    background: 'rgba(46,229,157,0.12)', border: `1px solid ${theme.accent.green}`,
    color: theme.accent.green, fontSize: 11, fontFamily: theme.font.mono, fontWeight: 500,
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
  meetingField: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 },
  miniLabel: {
    fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber,
    letterSpacing: '0.08em', textTransform: 'uppercase' as const,
  },
  briefGrid: {
    display: 'grid', gridTemplateColumns: '1fr 1fr',
    gap: 20, alignItems: 'start',
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
  contextInputReadonly: {
    padding: '10px 14px',
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.secondary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box' as const,
    cursor: 'default',
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
