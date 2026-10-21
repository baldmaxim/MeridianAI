import { Component, type ErrorInfo, type ReactNode } from 'react';
import styles from './ErrorBoundary.module.css';

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
      <div className={styles.wrap}>
        <div className={styles.card}>
          <div className={styles.title}>Что-то пошло не так</div>
          <div className={styles.msg}>{this.state.message}</div>
          <button className={styles.btn} onClick={() => { this.setState({ hasError: false, message: '' }); window.location.reload(); }}>
            Перезагрузить
          </button>
        </div>
      </div>
    );
  }
}
