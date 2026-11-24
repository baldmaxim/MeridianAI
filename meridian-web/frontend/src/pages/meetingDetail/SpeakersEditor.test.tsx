import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SpeakersEditor } from './SpeakersEditor';
import { buildSpeakerList, humanSpeakerLabel } from './speakerList';
import * as speakerRolesApi from '../../api/speakerRoles';
import * as finalizationApi from '../../api/finalization';
import type { SpeakerRoleOut, TranscriptSegmentRecord } from '../../types';

vi.mock('../../api/speakerRoles', () => ({ getSpeakerRoles: vi.fn(), putSpeakerRole: vi.fn() }));
vi.mock('../../api/finalization', () => ({ retryFinalization: vi.fn() }));

const seg = (id: string, label: string, text: string): TranscriptSegmentRecord => ({
  segment_id: id, text, speaker_id: label, speaker_label: label,
  start_time: 0, end_time: 1, wall_clock: '2026-11-24T10:00:00', origin: 'batch',
});

const SEGMENTS = [
  seg('1', 'Speaker_speaker_0', 'Добрый день'),
  seg('2', 'Speaker_speaker_1', 'Нужно обсудить сроки поставки арматуры и порядок оплаты по второму этапу работ'),
  seg('3', 'Speaker_speaker_0', 'Согласен'),
];

const role = (label: string, side: SpeakerRoleOut['side'], name: string | null): SpeakerRoleOut => ({
  id: 1, meeting_id: 7, speaker_label: label, side, display_name: name,
  assigned_by_user_id: null, created_at: '', updated_at: '',
});

describe('SpeakersEditor', () => {
  beforeEach(() => {
    vi.mocked(speakerRolesApi.getSpeakerRoles).mockResolvedValue([]);
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  const open = async () => {
    render(<SpeakersEditor meetingId={7} segments={SEGMENTS} onProtocolRebuild={onRebuild} />);
    await waitFor(() => expect(speakerRolesApi.getSpeakerRoles).toHaveBeenCalledWith(7));
    fireEvent.click(screen.getByRole('button', { name: /Спикеры/ }));
  };
  const onRebuild = vi.fn();

  it('по карточке на уникального спикера, с числом реплик', async () => {
    await open();
    expect(await screen.findAllByRole('group', { name: /Сторона/ })).toHaveLength(2);
    expect(screen.getByText('2 реплики')).toBeTruthy();
    expect(screen.getByText('1 реплика')).toBeTruthy();
  });

  it('клик «Мы» сохраняет сторону и подставляет ответ', async () => {
    const saved = [role('Speaker_speaker_0', 'self', null)];
    vi.mocked(speakerRolesApi.putSpeakerRole).mockResolvedValue(saved);
    await open();
    fireEvent.click((await screen.findAllByRole('button', { name: 'Мы' }))[0]);
    await waitFor(() => expect(speakerRolesApi.putSpeakerRole).toHaveBeenCalledWith(
      7, 'Speaker_speaker_0', expect.objectContaining({ side: 'self' }),
    ));
    expect(await screen.findByText('Имена и стороны попадут в протокол после пересборки')).toBeTruthy();
  });

  it('ошибка сохранения показывается строкой под карточкой', async () => {
    vi.mocked(speakerRolesApi.putSpeakerRole).mockRejectedValue(new Error('x'));
    await open();
    fireEvent.click((await screen.findAllByRole('button', { name: 'Оппонент' }))[0]);
    expect(await screen.findByRole('alert')).toBeTruthy();
  });

  it('«Пересобрать протокол» вызывает retryFinalization и onProtocolRebuild', async () => {
    vi.mocked(finalizationApi.retryFinalization).mockResolvedValue({
      meeting_id: 7, status: 'queued', error: null, finalized_at: null, has_protocol: false,
    });
    await open();
    fireEvent.click(await screen.findByRole('button', { name: 'Пересобрать протокол' }));
    await waitFor(() => expect(finalizationApi.retryFinalization).toHaveBeenCalledWith(7));
    await waitFor(() => expect(onRebuild).toHaveBeenCalledTimes(1));
  });

  it('без спикеров блок не показывается', () => {
    render(<SpeakersEditor meetingId={7} segments={[]} />);
    expect(screen.queryByRole('button', { name: /Спикеры/ })).toBeNull();
  });
});

describe('speakerList', () => {
  it('человекочитаемая метка', () => {
    expect(humanSpeakerLabel('Speaker_speaker_0')).toBe('Спикер 1');
    expect(humanSpeakerLabel('speaker_2')).toBe('Спикер 3');
    expect(humanSpeakerLabel('s1_speaker_0')).toBe('Спикер 1');
    expect(humanSpeakerLabel('Иван')).toBe('Иван');
  });

  it('пример — реплика 60–200 символов, иначе первая; порядок первого появления', () => {
    const list = buildSpeakerList(SEGMENTS);
    expect(list.map((s) => s.label)).toEqual(['Speaker_speaker_0', 'Speaker_speaker_1']);
    expect(list[0]).toMatchObject({ count: 2, sample: 'Добрый день' });
    expect(list[1].sample.startsWith('Нужно обсудить')).toBe(true);
  });
});
