import { useCallback, useEffect, useRef } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { getMeetingDetail } from '../../api/history';
import type { WSMessageToServer } from '../../types';
import { buildDefaultMeetingName } from './meetingFormat';

const CONTEXT_SEND_DELAY_MS = 350;

/**
 * Контекст встречи (название, тема, заметки, слабые стороны): дебаунс отправки на сервер,
 * дефолтное название и подтягивание темы после финализации.
 *
 * Локальный стор обновляется мгновенно (поле/шапка реагируют сразу), а update_meeting_context
 * уходит на сервер с задержкой — вместе с guard contextEditedAt это гасит self-echo
 * (символы не пропадают).
 */
export const useMeetingContextSync = (
  sendJSON: (msg: WSMessageToServer) => void,
  meetingName: string,
  customerName: string | null,
  objectName: string | null,
) => {
  const ctxSendTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => {
    if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current);
  }, []);

  // Единый отправитель контекста: читает ВСЕ поля из стора в момент отправки.
  // Поля раскиданы по разным карточкам — кортеж собрать неоткуда, поэтому источник
  // истины один (стор). markContextEdited + debounce 350ms гасят self-echo.
  const pushContext = useCallback(() => {
    useMeetingStore.getState().markContextEdited();
    if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current);
    ctxSendTimer.current = setTimeout(() => {
      const st = useMeetingStore.getState();
      sendJSON({ type: 'update_meeting_context', title: st.meetingName || undefined, topic: st.meetingTopic, notes: st.meetingNotes, negotiation_type: st.negotiationType, meeting_role: st.meetingRole, opponent_weaknesses: st.opponentWeaknesses });
    }, CONTEXT_SEND_DELAY_MS);
  }, [sendJSON]);

  const handleWeaknessesChange = useCallback((v: string) => {
    useMeetingStore.getState().setOpponentWeaknesses(v);
    pushContext();
  }, [pushContext]);

  const handleMeetingNameChange = useCallback((name: string) => {
    const s = useMeetingStore.getState();
    s.setMeetingName(name);
    s.markContextEdited();
    if (ctxSendTimer.current) clearTimeout(ctxSendTimer.current);
    ctxSendTimer.current = setTimeout(() => {
      const st = useMeetingStore.getState();
      sendJSON({ type: 'update_meeting_context', title: name, topic: st.meetingTopic, notes: st.meetingNotes, negotiation_type: st.negotiationType, meeting_role: st.meetingRole, opponent_weaknesses: st.opponentWeaknesses });
    }, CONTEXT_SEND_DELAY_MS);
  }, [sendJSON]);

  const handleMeetingTopicChange = useCallback((topic: string) => {
    useMeetingStore.getState().setMeetingTopic(topic);
    pushContext();
  }, [pushContext]);

  // Дефолт названия встречи «Заказчик_Объект_Дата» — только когда поле пустое и
  // известен заказчик/объект. Не затирает то, что пользователь уже ввёл/подтянуто из БД.
  useEffect(() => {
    if (meetingName) return;
    if (!customerName && !objectName) return;
    useMeetingStore.getState().setMeetingName(buildDefaultMeetingName(customerName, objectName));
  }, [meetingName, customerName, objectName]);

  // После финализации подтянуть тему/название из БД (тему ИИ ставит, только если она была пуста).
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

  return { pushContext, handleWeaknessesChange, handleMeetingNameChange, handleMeetingTopicChange, refreshMeetingMeta };
};
