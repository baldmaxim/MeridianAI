import { useState } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginPage } from './pages/LoginPage';
import { MeetingPage } from './pages/MeetingPage';
import { AdminPage } from './pages/AdminPage';
import { HistoryPage } from './pages/HistoryPage';
import { MeetingDetailPage } from './pages/MeetingDetailPage';
import { BatchPage } from './pages/BatchPage';
import { AppLayout } from './components/layout/AppLayout';

type Page = 'meeting' | 'admin' | 'history' | 'history-detail' | 'batch';

function App() {
  const { user, loading, login, register, logout } = useAuth();
  const [currentPage, setCurrentPage] = useState<Page>('meeting');
  const [selectedMeetingId, setSelectedMeetingId] = useState<number | null>(null);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#080A0F', color: '#EDF2FF' }}>
        Загрузка...
      </div>
    );
  }

  if (!user) {
    return <LoginPage onLogin={login} onRegister={register} />;
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'batch':
        return <BatchPage onBack={() => setCurrentPage('meeting')} />;
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
    >
      {renderPage()}
    </AppLayout>
  );
}

export default App;
