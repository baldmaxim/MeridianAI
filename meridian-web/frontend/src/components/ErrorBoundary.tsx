import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode; }
interface State { hasError: boolean; message: string; }

/** Глобальный предохранитель: ошибка рендера не «белит» весь экран (Этап 10). */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error?.message || 'Неизвестная ошибка' };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // не логируем потенциально чувствительные данные — только сообщение
    console.error('UI error:', error.message, info.componentStack?.slice(0, 200));
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div style={styles.wrap}>
        <div style={styles.card}>
          <div style={styles.title}>Что-то пошло не так</div>
          <div style={styles.msg}>{this.state.message}</div>
          <button style={styles.btn} onClick={() => { this.setState({ hasError: false, message: '' }); window.location.reload(); }}>
            Перезагрузить
          </button>
        </div>
      </div>
    );
  }
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#080A0F', color: '#EDF2FF', fontFamily: 'Inter, system-ui, sans-serif' },
  card: { display: 'flex', flexDirection: 'column', gap: 14, padding: 32, background: '#111520', border: '1px solid #1A2135', borderRadius: 14, maxWidth: 440, textAlign: 'center' as const },
  title: { fontSize: 18, fontWeight: 800, color: '#F5A623' },
  msg: { fontSize: 13, color: '#8896B3', wordBreak: 'break-word' as const },
  btn: { padding: '10px 18px', background: '#F5A623', border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
};
