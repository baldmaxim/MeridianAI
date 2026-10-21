import { useState, useEffect, useCallback, useRef } from 'react';
import type { FC } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { SideCalibration } from '../components/meeting/SideCalibration';
import { useSelfHold } from '../hooks/useSelfHold';
import { useMeetingStore } from '../store/meetingStore';
import { getSettings } from '../api/settings';
import { createMeeting } from '../api/meetings';
import { getMeetingDetail } from '../api/history';
import { getConversationTree } from '../api/conversationTree';
import { HelperPanel } from '../components/meeting/HelperPanel';
import { ParticipantsBadge } from '../components/meeting/ParticipantsBadge';
import { ControlButtons } from '../components/meeting/ControlButtons';
import { DictaphoneView } from '../components/meeting/DictaphoneView';
import { OfflineBanner } from '../components/meeting/OfflineBanner';
import { navigate, paths } from '../lib/navigation';
import type { UserSettings } from '../types';
import { buildDefaultMeetingName, formatMeetingDate } from './meeting/meetingFormat';
import { MeetingTopBar } from './meeting/MeetingTopBar';
import { MeetingToast } from './meeting/MeetingToast';
import type { IMeetingToastData } from './meeting/MeetingToast';
import { RecordingBanner } from './meeting/RecordingBanner';
import { NegotiationsTab } from './meeting/NegotiationsTab';
import { MeetingContextTab } from './meeting/MeetingContextTab';
import { useMeetingSpeakers } from './meeting/useMeetingSpeakers';
import { useMeetingContextSync } from './meeting/useMeetingContextSync';
import { useMeetingAudioCapture } from './meeting/useMeetingAudioCapture';
import styles from './MeetingPage.module.css';

const TABS = ['Переговоры', 'Контекст встречи'] as const;
const TOAST_MS = 3000;
const SAVE_COOLDOWN_MS = 2000;

interface IMeetingPageProps {
  meetingId?: number;
  onBack: () => void;
}

export const MeetingPage: FC<IMeetingPageProps> = ({ meetingId, onBack }) => {
  const [activeTab, setActiveTab] = useState(0);
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [toast, setToast] = useState<IMeetingToastData | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), TOAST_MS);
  }, []);

  const { connect, disconnect, sendJSON, sendBinary, ws } = useWebSocket(() => {
    // Встреча удалена на сервере — на главный экран
    showToast('Встреча удалена', 'error');
    navigate(paths.objects);
  });
  const getSocket = useCallback(() => ws.current, [ws]);
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

  const audio = useMeetingAudioCapture({
    sendJSON, sendBinary, getSocket, isConnected: store.isConnected, showToast, startSession, waitForConnected,
  });
  const { handleStartListening, handleStopListening } = audio;
  const speakers = useMeetingSpeakers(store.currentMeetingId, sendJSON);
  const { pushContext, handleWeaknessesChange, handleMeetingNameChange, refreshMeetingMeta } = useMeetingContextSync(
    sendJSON, store.meetingName, store.selectedCustomerName, store.selectedObjectName,
  );

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
      useMeetingStore.getState().setCustomSuggestionTypes(s.custom_suggestion_types);
      // дефолт числа спикеров (до live meeting_settings_updated по WS)
      useMeetingStore.getState().setMaxSpeakers(s.diarization_max_speakers || 3);
    }).catch(() => {});
    return () => {
      disconnect();
    };
    // Только при монтировании: встреча/подключение выбираются один раз при заходе на страницу.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Conversation Tree: начальная загрузка дерева при открытии встречи
  useEffect(() => {
    if (store.currentMeetingId == null) return;
    getConversationTree(store.currentMeetingId)
      .then((tree) => useMeetingStore.getState().setConversationTree(tree.topics, tree.tree_version, tree.unassigned_speakers))
      .catch(() => {});
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

  // Калибровка сторон «держу — говорим мы»: очная встреча на провайдере с диаризацией.
  // В онлайне сторону даёт источник звука, у ElevenLabs нет меток голосов — там не нужна.
  const diarizationAvailable = (settings?.stt_provider === 'deepgram' || settings?.stt_provider === 'speechmatics')
    && !!settings?.diarization;
  const sideCalibrationOn = store.isListening && !audio.systemAudioState?.active && diarizationAvailable;
  const selfHold = useSelfHold(sideCalibrationOn, sendJSON);
  // Каждый старт записи — новая нумерация голосов у провайдера: считаем реплики с этого места.
  const [sessionMsgStart, setSessionMsgStart] = useState(0);
  const [prevListening, setPrevListening] = useState(store.isListening);
  if (store.isListening !== prevListening) {
    setPrevListening(store.isListening);
    if (store.isListening) setSessionMsgStart(store.messages.length);
  }

  const [savingMeeting, setSavingMeeting] = useState(false);

  const handleSaveMeeting = useCallback(() => {
    if (savingMeeting) return;
    setSavingMeeting(true);
    sendJSON({ type: 'finalize_meeting', meeting_name: store.meetingName || undefined });
    showToast('Встреча сохранена', 'success');
    setTimeout(() => setSavingMeeting(false), SAVE_COOLDOWN_MS);
  }, [sendJSON, store.meetingName, savingMeeting, showToast]);

  const handleRoleSelect = useCallback((roleId: number) => {
    sendJSON({ type: 'change_role', role_id: roleId });
  }, [sendJSON]);

  const topBar = (
    <MeetingTopBar
      onBack={onBack}
      customerName={store.selectedCustomerName}
      objectName={store.selectedObjectName}
      // Дата встречи (начало записи) для шапки.
      meetingDate={formatMeetingDate(store.meetingStartedAt)}
      meetingId={store.currentMeetingId}
      showToast={showToast}
      audioSettings={{
        onConfigChange: audio.onAudioCaptureConfig,
        enabled: audio.onlineAudio,
        onToggle: audio.handleOnlineAudioToggle,
        state: audio.systemAudioState,
        levels: audio.sourceLevels,
        isListening: store.isListening,
      }}
    />
  );

  // key меняется на каждый рендер — как и раньше, тост проигрывает анимацию заново
  const toastEl = toast && <MeetingToast key={toast.message + Date.now()} toast={toast} />;

  const recordingBanner = (
    <RecordingBanner
      recordingPaused={audio.recordingPaused}
      isListening={store.isListening}
      onResume={audio.handleResumeListening}
    />
  );

  const sideCalibration = (compact: boolean) => sideCalibrationOn && (
    <SideCalibration
      sinceIndex={sessionMsgStart}
      holding={selfHold.holding}
      onPress={selfHold.press}
      onRelease={selfHold.release}
      onSetSide={speakers.handleSetSpeakerSide}
      compact={compact}
    />
  );

  // Простой режим (вид «Пользователь») — чистый диктофон поверх той же сессии.
  // Переключение режима — единым слайдером роли «Админ ⟷ Пользователь» в шапке.
  if (store.uiMode === 'simple') {
    return (
      <div className={styles.container}>
        {topBar}
        <OfflineBanner />
        {recordingBanner}
        <HelperPanel />
        <DictaphoneView
          level={audio.level}
          isListening={store.isListening}
          isConnected={store.isConnected}
          onStart={handleStartListening}
          onStop={handleStopListening}
          extra={sideCalibration(false)}
        />
        {toastEl}
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {topBar}
      <OfflineBanner />
      {recordingBanner}
      <HelperPanel />
      {/* Tab bar + бейдж участников справа */}
      <div className={`meeting-tabs ${styles.tabs}`}>
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            className={`t-btn ${styles.tab}${activeTab === i ? ` ${styles.tabActive}` : ''}`}
          >
            {tab}
          </button>
        ))}
        <ParticipantsBadge />
      </div>

      {/* Tab content */}
      <div className={activeTab === 0 ? styles.contentNegotiations : styles.content}>
        {activeTab === 0 && (
          <NegotiationsTab
            drawerOpen={drawerOpen}
            onCloseDrawer={() => setDrawerOpen(false)}
            speakers={speakers}
            canSetMaxSpeakers={diarizationAvailable}
            onSaveToHistory={() => sendJSON({ type: 'save_to_history' })}
          />
        )}
        {activeTab === 1 && (
          <MeetingContextTab
            pushContext={pushContext}
            onMeetingNameChange={handleMeetingNameChange}
            onWeaknessesChange={handleWeaknessesChange}
            onRoleSelect={handleRoleSelect}
            onSaveMeeting={handleSaveMeeting}
            savingMeeting={savingMeeting}
            onFinalized={refreshMeetingMeta}
            startSession={startSession}
          />
        )}
      </div>

      {activeTab === 0 && sideCalibration(true)}

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
};
