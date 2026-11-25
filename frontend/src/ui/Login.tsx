import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type DemoUser, type User } from '../api';

export function Login({ onLogin, notice }: { onLogin: (u: User) => void; notice?: string | null }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<DemoUser[]>([]);
  const userRef = useRef<HTMLInputElement>(null);
  const passRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .demoUsers()
      .then((r) => setDemo(r.users))
      .catch(() => setDemo([]));
    userRef.current?.focus();
  }, []);

  const submit = async (u: string, p: string) => {
    const errs: Record<string, string> = {};
    if (!u.trim()) errs.username = 'Введите логин';
    if (!p) errs.password = 'Введите пароль';
    setErrors(errs);
    if (errs.username) return userRef.current?.focus();
    if (errs.password) return passRef.current?.focus();
    setBusy(true);
    try {
      const r = await api.login(u, p);
      onLogin(r.user);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Не удалось войти';
      setErrors({ password: msg });
      passRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <section className="card" aria-labelledby="login-heading">
        <h1 id="login-heading">Вход</h1>
        {notice && (
          <p className="banner banner--warn" role="status">
            {notice}
          </p>
        )}
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void submit(username, password);
          }}
        >
          <div className="field">
            <label htmlFor="login-user">Логин</label>
            <input
              id="login-user"
              ref={userRef}
              autoComplete="username"
              value={username}
              aria-invalid={Boolean(errors.username)}
              aria-describedby={errors.username ? 'e-user' : undefined}
              onChange={(e) => setUsername(e.target.value)}
            />
            {errors.username && (
              <p id="e-user" className="error">
                {errors.username}
              </p>
            )}
          </div>
          <div className="field">
            <label htmlFor="login-pass">Пароль</label>
            <input
              id="login-pass"
              ref={passRef}
              type="password"
              autoComplete="current-password"
              value={password}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? 'e-pass' : undefined}
              onChange={(e) => setPassword(e.target.value)}
            />
            {errors.password && (
              <p id="e-pass" className="error">
                {errors.password}
              </p>
            )}
          </div>
          <button type="submit" className="btn btn--primary btn--wide" disabled={busy}>
            {busy ? 'Входим…' : 'Войти'}
          </button>
        </form>
      </section>

      {demo.length > 0 && (
        <section className="card" aria-labelledby="demo-heading">
          <h2 id="demo-heading">Демо-входы</h2>
          <p className="hint">Локальная демоверсия. Пароль организатора — «{demo.find((d) => d.role === 'organizer')?.password}», участников — «{demo.find((d) => d.role === 'participant')?.password}».</p>
          <ul className="demo-users">
            {demo.map((d) => (
              <li key={d.username}>
                <button type="button" className={d.role === 'organizer' ? 'btn btn--primary' : 'btn'} onClick={() => void submit(d.username, d.password)}>
                  {d.display_name} <span className="muted">· {d.role === 'organizer' ? 'организатор' : d.username}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
