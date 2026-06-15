import { useState } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginPage } from './pages/LoginPage';
import { MeetingPage } from './pages/MeetingPage';
import { AdminPage } from './pages/AdminPage';
import { HistoryPage } from './pages/HistoryPage';
import { MeetingDetailPage } from './pages/MeetingDetailPage';
import { BatchPage } from './pages/BatchPage';
import { DirectoryPage } from './pages/DirectoryPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { AppLayout } from './components/layout/AppLayout';
import { RecorderPage } from './pages/RecorderPage';
import { MobileMeetingsPage } from './pages/mobile/MobileMeetingsPage';
import { MobileMeetingDetailPage } from './pages/mobile/MobileMeetingDetailPage';
import { usePathname, parseRoute } from './lib/navigation';

type Page = 'meeting' | 'admin' | 'history' | 'history-detail' | 'batch' | 'directory' | 'knowledge';

function App() {
  const { user, loading, login, register, logout } = useAuth();
  const [currentPage, setCurrentPage] = useState<Page>('meeting');
  const [selectedMeetingId, setSelectedMeetingId] = useState<number | null>(null);
  const pathname = usePathname();
  const route = parseRoute(pathname);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#080A0F', color: '#EDF2FF' }}>
        Загрузка...
      </div>
    );
  }

  // Авторизация: при заходе на mobile/recorder без токена показываем логин;
  // pathname сохраняется → после входа рендерится исходный маршрут.
  if (!user) {
    return <LoginPage onLogin={login} onRegister={register} />;
  }

  // Этап 3: мобильные маршруты по URL (для прямых ссылок/QR)
  if (route.kind === 'recorder') {
    return <RecorderPage meetingId={route.meetingId} />;
  }
  if (route.kind === 'mobile-list') {
    return <MobileMeetingsPage userName={user.display_name || user.email} onLogout={logout} />;
  }
  if (route.kind === 'mobile-detail') {
    return <MobileMeetingDetailPage meetingId={route.meetingId} />;
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'batch':
        return <BatchPage onBack={() => setCurrentPage('meeting')} />;
      case 'directory':
        return <DirectoryPage onBack={() => setCurrentPage('meeting')} />;
      case 'knowledge':
        return <KnowledgePage onBack={() => setCurrentPage('meeting')} />;
      case 'admin':
        return <AdminPage onBack={() => setCurrentPage('meeting')} />;
      case 'history':
        return (
          <HistoryPage
            onBack={() => setCurrentPage('meeting')}
            onSelectMeeting={(id) => {
              setSelectedMeetingId(id);
              setCurrentPage('history-detail');
            }}
          />
        );
      case 'history-detail':
        return (
          <MeetingDetailPage
            meetingId={selectedMeetingId!}
            onBack={() => setCurrentPage('history')}
            onContinue={() => setCurrentPage('meeting')}
          />
        );
      default:
        return <MeetingPage />;
    }
  };

  return (
    <AppLayout
      userName={user.display_name || user.email}
      userRole={user.role}
      onLogout={logout}
      showAdmin={currentPage === 'admin'}
      onToggleAdmin={user.role === 'admin' ? () => setCurrentPage(currentPage === 'admin' ? 'meeting' : 'admin') : undefined}
      onShowHistory={() => setCurrentPage(currentPage === 'history' || currentPage === 'history-detail' ? 'meeting' : 'history')}
      showHistory={currentPage === 'history' || currentPage === 'history-detail'}
      onShowBatch={() => setCurrentPage(currentPage === 'batch' ? 'meeting' : 'batch')}
      showBatch={currentPage === 'batch'}
      onShowDirectory={() => setCurrentPage(currentPage === 'directory' ? 'meeting' : 'directory')}
      showDirectory={currentPage === 'directory'}
      onShowKnowledge={() => setCurrentPage(currentPage === 'knowledge' ? 'meeting' : 'knowledge')}
      showKnowledge={currentPage === 'knowledge'}
    >
      {renderPage()}
    </AppLayout>
  );
}

export default App;
