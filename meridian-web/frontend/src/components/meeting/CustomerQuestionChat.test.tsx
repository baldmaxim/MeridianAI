import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AxiosError } from 'axios';
import { useMeetingStore } from '../../store/meetingStore';
import { askMeeting } from '../../api/meetings';
import { CustomerQuestionChat } from './CustomerQuestionChat';

vi.mock('../../api/meetings', () => ({ askMeeting: vi.fn() }));

const askMock = vi.mocked(askMeeting);

beforeEach(() => {
  useMeetingStore.setState({ currentMeetingId: 7 });
  askMock.mockReset();
});

afterEach(cleanup);

describe('CustomerQuestionChat', () => {
  it('клик по чипу вызывает askMeeting (anticipate) и выводит ответ с <strong>', async () => {
    askMock.mockResolvedValue({
      answer: '**Ответ:** цена включает монтаж\n**Опора:**\n- КП, раздел 2',
      sources: [{ kind: 'document', title: 'КП', ref: 'стр. 3' }],
    });
    render(<CustomerQuestionChat />);
    await userEvent.click(screen.getByRole('button', { name: 'Почему так дорого?' }));
    expect(askMock).toHaveBeenCalledWith(7, 'Почему так дорого?', 'anticipate');
    const strong = await screen.findByText('Ответ:');
    expect(strong.tagName).toBe('STRONG');
    expect(screen.getByText('КП, раздел 2').tagName).toBe('LI');
    expect(screen.getByText('КП · стр. 3')).toBeTruthy();
  });

  it('ошибка без detail показывает запасной текст', async () => {
    askMock.mockRejectedValueOnce(new Error('network'));
    render(<CustomerQuestionChat />);
    await userEvent.click(screen.getByRole('button', { name: 'Какие сроки и график?' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Не удалось получить ответ');
  });

  it('ошибка сервера показывает текст из detail', async () => {
    const err = new AxiosError('fail', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 429, statusText: '', headers: {}, config: {} as never, data: { detail: 'Слишком много запросов' },
    });
    askMock.mockRejectedValueOnce(err);
    render(<CustomerQuestionChat />);
    await userEvent.click(screen.getByRole('button', { name: 'Что не входит в КП?' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Слишком много запросов');
  });

  it('без встречи всё disabled и показана подсказка', () => {
    useMeetingStore.setState({ currentMeetingId: null });
    render(<CustomerQuestionChat />);
    expect(screen.getByText('Откройте или начните встречу')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Почему так дорого?' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('textbox') as HTMLInputElement).disabled).toBe(true);
  });
});
