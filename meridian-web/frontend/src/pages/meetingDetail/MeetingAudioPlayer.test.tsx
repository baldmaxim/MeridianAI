import { afterEach, describe, it, expect, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MeetingAudioPlayer } from './MeetingAudioPlayer';
import * as historyApi from '../../api/history';
import type { MeetingAudioPart } from '../../types';

vi.mock('../../api/history', () => ({ getMeetingAudio: vi.fn() }));

const part = (name: string, url: string, source: MeetingAudioPart['source'] = 'live'): MeetingAudioPart => ({
  name, url, source, expires_in: 21600,
});

const audioEl = (container: HTMLElement) => container.querySelector('audio') as HTMLAudioElement;

describe('MeetingAudioPlayer', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('нет записи — ничего не рисует', async () => {
    vi.mocked(historyApi.getMeetingAudio).mockResolvedValue(null);
    const { container } = render(<MeetingAudioPlayer meetingId={7} />);
    await waitFor(() => expect(historyApi.getMeetingAudio).toHaveBeenCalledWith(7));
    expect(container.innerHTML).toBe('');
  });

  it('одна часть: плеер без чипов', async () => {
    vi.mocked(historyApi.getMeetingAudio).mockResolvedValue([part('rec.mp3', 'https://s3/a', 'batch')]);
    const { container } = render(<MeetingAudioPlayer meetingId={7} />);
    await waitFor(() => expect(audioEl(container)).toBeTruthy());
    expect(audioEl(container).getAttribute('src')).toBe('https://s3/a');
    expect(audioEl(container).getAttribute('preload')).toBe('metadata');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('две части: чипы, переключение меняет src', async () => {
    vi.mocked(historyApi.getMeetingAudio).mockResolvedValue([
      part('Часть 1', 'https://s3/1'), part('Часть 2', 'https://s3/2'),
    ]);
    const { container } = render(<MeetingAudioPlayer meetingId={7} />);
    const second = await screen.findByRole('button', { name: 'Часть 2' });
    const first = screen.getByRole('button', { name: 'Часть 1' });
    expect(first.getAttribute('aria-pressed')).toBe('true');
    expect(audioEl(container).getAttribute('src')).toBe('https://s3/1');

    fireEvent.click(second);
    expect(second.getAttribute('aria-pressed')).toBe('true');
    expect(first.getAttribute('aria-pressed')).toBe('false');
    expect(audioEl(container).getAttribute('src')).toBe('https://s3/2');
  });

  it('ошибка загрузки частей — «Запись недоступна»', async () => {
    vi.mocked(historyApi.getMeetingAudio).mockRejectedValue(new Error('500'));
    render(<MeetingAudioPlayer meetingId={7} />);
    expect(await screen.findByText('Запись недоступна')).toBeTruthy();
  });

  it('ошибка audio: один перезапрос ссылок, повторная — «Запись недоступна»', async () => {
    vi.mocked(historyApi.getMeetingAudio)
      .mockResolvedValueOnce([part('rec.mp3', 'https://s3/old', 'batch')])
      .mockResolvedValueOnce([part('rec.mp3', 'https://s3/new', 'batch')]);
    const { container } = render(<MeetingAudioPlayer meetingId={7} />);
    await waitFor(() => expect(audioEl(container)).toBeTruthy());

    fireEvent.error(audioEl(container));
    await waitFor(() => expect(audioEl(container).getAttribute('src')).toBe('https://s3/new'));
    expect(historyApi.getMeetingAudio).toHaveBeenCalledTimes(2);

    fireEvent.error(audioEl(container));
    expect(await screen.findByText('Запись недоступна')).toBeTruthy();
    expect(historyApi.getMeetingAudio).toHaveBeenCalledTimes(2);
  });
});
