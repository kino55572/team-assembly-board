import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, type User } from './api';
import { Login } from './ui/Login';
import { OrganizerView } from './ui/OrganizerView';
import { ParticipantView } from './ui/ParticipantView';

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const [loginNotice, setLoginNotice] = useState<string | null>(null);

  const announce = useCallback((text: string) => {
    setAnnouncement('');
    window.setTimeout(() => setAnnouncement(text), 30);
  }, []);

  useEffect(() => {
    api
      .me()
      .then((r) => setUser(r.user))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status !== 401) setFatal(e.message);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const lost = () => {
      setUser(null);
      setLoginNotice('Сессия закончилась — войдите снова');
    };
    window.addEventListener('auth-lost', lost);
    return () => window.removeEventListener('auth-lost', lost);
  }, []);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setUser(null);
    announce('Вы вышли');
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            ◫
          </span>
          <div>
            <p className="brand__name">Доска сборки команд</p>
            <p className="brand__sub">Отклики участников → роли в командах</p>
          </div>
        </div>
        {user && (
          <div className="whoami">
            <span data-testid="whoami">
              {user.display_name} · {user.role === 'organizer' ? 'организатор' : 'участник'}
            </span>
            <button type="button" className="btn btn--sm" onClick={() => void logout()}>
              Выйти
            </button>
          </div>
        )}
      </header>
      {fatal && (
        <p className="banner banner--err" role="alert">
          {fatal}
        </p>
      )}
      {loading ? (
        <p className="muted center">Загрузка…</p>
      ) : !user ? (
        <Login
          notice={loginNotice}
          onLogin={(u) => {
            setLoginNotice(null);
            setUser(u);
            announce(`Вы вошли как ${u.display_name}`);
          }}
        />
      ) : user.role === 'organizer' ? (
        <OrganizerView announce={announce} />
      ) : (
        <ParticipantView user={user} announce={announce} />
      )}
      <footer className="footer">Демоверсия: все имена вымышленные. Данные хранятся в SQLite на сервере.</footer>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-testid="announcer">
        {announcement}
      </div>
    </div>
  );
}
