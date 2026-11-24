import { useState } from 'react';
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MeetingMainWindow } from './MeetingMainWindow';
import type { TMainTab } from './MeetingMainWindow';
import * as speakerRolesApi from '../../api/speakerRoles';
import * as finalizationApi from '../../api/finalization';
import type { TranscriptSegmentRecord } from '../../types';

vi.mock('../../api/speakerRoles', () => ({ getSpeakerRoles: vi.fn(), putSpeakerRole: vi.fn() }));
vi.mock('../../api/finalization', () => ({
  getFinalizationStatus: vi.fn(),
  getMeetingProtocol: vi.fn(),
  retryFinalization: vi.fn(),
}));

const seg = (id: string, label: string, text: string): TranscriptSegmentRecord => ({
  segment_id: id, text, speaker_id: label, speaker_label: label,
  start_time: 0, end_time: 1, wall_clock: '2026-11-24T10:00:00', origin: 'batch',
});

const Harness = ({ segments }: { segments: TranscriptSegmentRecord[] }) => {
  const [tab, setTab] = useState<TMainTab>('transcript');
  return (
    <MeetingMainWindow
      meetingId={7}
      segments={segments}
      rolesByLabel={new Map()}
      tab={tab}
      onTabChange={setTab}
      showSwitch
      protocolRefresh={0}
      onRolesChange={() => {}}
      onProtocolRebuild={() => {}}
    />
  );
};

const pages = (container: HTMLElement) => container.querySelector('[data-page]') as HTMLElement;

describe('MeetingMainWindow', () => {
  beforeEach(() => {
    vi.mocked(speakerRolesApi.getSpeakerRoles).mockResolvedValue([]);
    vi.mocked(finalizationApi.getFinalizationStatus).mockResolvedValue({
      meeting_id: 7, status: 'not_started', error: null, finalized_at: null, has_protocol: false,
    });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('переключает «Транскрипт» ↔ «Протокол»: aria-selected, слайд и inert', async () => {
    const { container } = render(<Harness segments={[seg('1', 'Speaker_speaker_0', 'Добрый день')]} />);
    const transcriptTab = screen.getByRole('tab', { name: 'Транскрипт' });
    const protocolTab = screen.getByRole('tab', { name: 'Протокол' });
    const pageOne = container.querySelector('[data-page-id="1"]') as HTMLElement;
    const pageTwo = container.querySelector('[data-page-id="2"]') as HTMLElement;

    expect(transcriptTab.getAttribute('aria-selected')).toBe('true');
    expect(pages(container).dataset.page).toBe('1');
    expect(pageOne.hasAttribute('inert')).toBe(false);
    expect(pageTwo.hasAttribute('inert')).toBe(true);

    fireEvent.click(protocolTab);
    expect(protocolTab.getAttribute('aria-selected')).toBe('true');
    expect(transcriptTab.getAttribute('aria-selected')).toBe('false');
    expect(pages(container).dataset.page).toBe('2');
    expect(pageOne.hasAttribute('inert')).toBe(true);
    expect(pageTwo.hasAttribute('inert')).toBe(false);
    expect(await screen.findByRole('button', { name: 'Собрать протокол' })).toBeTruthy();

    fireEvent.click(transcriptTab);
    expect(pages(container).dataset.page).toBe('1');
  });

  it('без транскрипта: «Нет данных транскрипции», полоса спикеров скрыта', async () => {
    render(<Harness segments={[]} />);
    expect(screen.getByText('Нет данных транскрипции')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Спикеры/ })).toBeNull();
    await waitFor(() => expect(finalizationApi.getFinalizationStatus).toHaveBeenCalledWith(7));
  });
});
