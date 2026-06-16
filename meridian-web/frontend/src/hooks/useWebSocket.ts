import { useRef, useCallback, useEffect } from 'react';
import { useMeetingStore } from '../store/meetingStore';
import type { WSMessageFromServer, WSMessageToServer } from '../types';

function getWsBase() {
  const env = import.meta.env.VITE_WS_URL;
  if (env) return env;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

interface ConnectOpts {
  meetingId?: number;
  deviceRole?: 'desktop' | 'phone' | 'viewer' | 'participant';
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const closedIntentionally = useRef(false);
  const connectOpts = useRef<ConnectOpts>({});

  const connect = useCallback((opts?: ConnectOpts) => {
    const token = localStorage.getItem('token');
    if (!token) return;
    if (opts) connectOpts.current = opts;

    const { meetingId, deviceRole = 'desktop' } = connectOpts.current;
    closedIntentionally.current = false;
    // Этап 2: по возможности подключаемся к конкретной встрече; иначе — legacy fallback
    const url = meetingId != null
      ? `${getWsBase()}/ws/meetings/${meetingId}?token=${token}&device_role=${deviceRole}`
      : `${getWsBase()}/ws/meeting?token=${token}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      const s = useMeetingStore.getState();
      s.setConnected(true);
      s.setStatus('Подключено к серверу');
      s.setError(null);
    };

    ws.onclose = () => {
      const s = useMeetingStore.getState();
      s.setConnected(false);
      s.setRoomConnected(false);
      s.setStatus('Отключено от сервера');
      // Auto-reconnect only if not intentionally closed
      if (!closedIntentionally.current) {
        reconnectTimer.current = setTimeout(() => connect(), 3000);
      }
    };

    ws.onerror = () => {
      useMeetingStore.getState().setError('Ошибка WebSocket соединения');
    };

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const data: WSMessageFromServer = JSON.parse(event.data);
          handleMessage(data);
        } catch {
          console.error('Invalid WS message:', event.data);
        }
      }
    };
  }, []);

  const disconnect = useCallback(() => {
    closedIntentionally.current = true;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    useMeetingStore.getState().setConnected(false);
  }, []);

  const sendJSON = useCallback((msg: WSMessageToServer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const sendBinary = useCallback((data: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  function handleMessage(data: WSMessageFromServer) {
    const s = useMeetingStore.getState();

    switch (data.type) {
      case 'transcript':
        if (data.is_partial) {
          s.updatePartial({
            id: '',
            speaker: data.speaker,
            text: data.text,
            timestamp: data.timestamp,
            is_partial: true,
          });
        } else {
          // Legacy format (Deepgram/Gemini) — add as regular message
          // For ElevenLabs, committed_transcript handles this
          s.clearPartial();
          s.addMessage({
            id: '',
            speaker: data.speaker,
            text: data.text,
            timestamp: data.timestamp,
            is_partial: false,
          });
        }
        break;

      case 'committed_transcript':
        // ElevenLabs committed segment with word-level data
        s.clearPartial();
        s.addCommittedSegment({
          segment_id: data.segment_id,
          speaker: data.speaker,
          text: data.text,
          words: data.words,
          start_time: data.start_time,
          end_time: data.end_time,
          confidence: data.confidence,
          timestamp: data.timestamp,
        });
        break;

      case 'batch_finalized':
        s.replaceBatchSegments(data.segments);
        break;

      case 'suggestion':
        if (data.cards && data.cards.length > 0) {
          // Этап 6: структурированные карточки
          for (const card of data.cards) {
            s.addSuggestion({
              text: card.text,
              is_auto: card.source_mode === 'auto',
              timestamp: new Date(),
              type: card.type,
              trigger: card.trigger ?? undefined,
              confidence: Math.round(card.confidence * 100),
              card,
            });
          }
        } else {
          // backward-compat: старый формат
          s.addSuggestion({
            text: data.text,
            is_auto: data.is_auto,
            timestamp: new Date(),
            type: data.suggestion_type,
            trigger: data.trigger,
            confidence: data.confidence,
            context_info: data.context_info,
          });
        }
        break;

      case 'strengthen_summary':
        for (const card of data.cards) {
          s.addSuggestion({
            text: card.text, is_auto: false, timestamp: new Date(),
            type: card.type, confidence: Math.round(card.confidence * 100), card,
          });
        }
        break;

      case 'analysis_status':
        s.setAnalysisStatus(data.status);
        break;

      case 'suggestion_chunk':
        s.setStreamingText(data.text);
        break;

      case 'suggestion_loading':
        if (data.loading) {
          s.setStreamingText(null);
        }
        s.setSuggestionLoading(data.loading);
        if (!data.loading) {
          s.setAnalysisStatus(null);
          if (s.currentStreamingText) {
            s.addSuggestion({
              text: s.currentStreamingText,
              is_auto: false,
              timestamp: new Date(),
              type: 'priority',
            });
          }
        }
        break;

      case 'strengthen_loading':
        if (data.loading) {
          s.setStreamingText(null);
        }
        s.setStrengthenLoading(data.loading);
        if (!data.loading) {
          s.setAnalysisStatus(null);
          if (s.currentStreamingText) {
            s.addSuggestion({
              text: s.currentStreamingText,
              is_auto: false,
              timestamp: new Date(),
              type: 'priority',
            });
          }
        }
        break;

      case 'meeting_context':
      case 'meeting_context_updated':
        if (data.title) s.setMeetingName(data.title);
        s.setMeetingTopic(data.topic);
        s.setMeetingNotes(data.notes);
        s.setNegotiationType(data.negotiation_type);
        s.setMeetingRole(data.meeting_role);
        s.setOpponentWeaknesses(data.opponent_weaknesses);
        break;

      case 'meeting_saved':
        s.setMeetingSavedId(data.meeting_id);
        break;

      // --- Этап 2: MeetingRoom / multi-device ---
      case 'room_joined':
        s.setCurrentMeetingId(data.meeting_id);
        s.setRoomJoined({
          connectionId: data.connection_id,
          deviceRole: data.device_role,
          canSendAudio: data.can_send_audio,
          activeAudioSource: data.active_audio_source,
        });
        break;

      case 'device_joined':
        s.setStatus('Подключено устройство к встрече');
        break;

      case 'device_left':
        break;

      case 'recording_status':
        s.setRecording(data.recording);
        s.setActiveAudioSource(data.active_audio_source);
        if (data.recording) s.setRecordPermissionDenied(false);
        break;

      case 'audio_source_busy':
        s.setError('Источник аудио занят другим устройством');
        break;

      case 'record_permission_denied':
        s.setRecordPermissionDenied(true);
        s.setListening(false);
        s.setError(data.message);
        break;

      case 'phone_recording_started':
        s.setPhoneRecording(true);
        s.setRecording(true);
        break;

      case 'phone_recording_stopped':
        s.setPhoneRecording(false);
        break;

      case 'audio_source_disconnected':
        s.setActiveAudioSource(null);
        s.setRecording(false);
        s.setListening(false);
        s.setStatus('Источник аудио отключился');
        break;

      case 'room_status':
        if (data.status === 'finalized') s.setStatus('Встреча завершена');
        break;

      case 'speaker_roles_updated':
        s.setSpeakerRoles(data.roles);
        break;

      case 'turn_update':
        s.handleTurnUpdate({
          turn_id: data.turn_id,
          speaker: data.speaker,
          text: data.text,
          start_time: data.start_time,
          end_time: data.end_time,
          timestamp: data.timestamp,
          segment_count: data.segment_count,
        });
        break;

      case 'turns_reset':
        s.resetTurns();
        break;

      case 'conversation_tree_updated':
        s.upsertConversationTopic(data.topic, data.tree_version);
        break;

      case 'error':
        s.setError(data.message);
        break;

      case 'status':
        s.setStatus(data.message);
        break;
    }
  }

  useEffect(() => {
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, []);

  return { connect, disconnect, sendJSON, sendBinary, ws: wsRef };
}
