import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type MyStatus, type RecruitmentListItem, type User } from '../api';
import { parseSkills } from '../board-logic';

const POLL_MS = 10000;

export function ParticipantView({ user, announce }: { user: User; announce: (t: string) => void }) {
  const [list, setList] = useState<RecruitmentListItem[]>([]);
  const [rid, setRid] = useState<number | null>(null);
  const [my, setMy] = useState<MyStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .recruitments()
      .then((r) => {
        setList(r.recruitments);
        setRid(r.recruitments[0]?.id ?? null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить наборы'));
  }, []);

  const load = useCallback(async () => {
    if (rid === null) return;
    try {
      setMy(await api.my(rid));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить данные');
    }
  }, [rid]);

  useEffect(() => {
    void load();
    const tick = () => document.visibilityState === 'visible' && void load();
    const h = setInterval(tick, POLL_MS);
    window.addEventListener('focus', tick);
    return () => {
      clearInterval(h);
      window.removeEventListener('focus', tick);
    };
  }, [load]);

  return (
    <main className="participant">
      {list.length > 1 && (
        <div className="field field--inline">
          <label htmlFor="p-rec">Набор</label>
          <select id="p-rec" value={rid ?? ''} onChange={(e) => setRid(Number(e.target.value))}>
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
        </div>
      )}
      {error && (
        <p className="banner banner--err" role="alert">
          {error}
        </p>
      )}
      {rid === null && list.length === 0 && !error && <p className="muted">Открытых наборов сейчас нет.</p>}
      {my && (
        <>
          <section className="card" aria-labelledby="rec-heading">
            <h1 id="rec-heading">{my.recruitment.title}</h1>
            {my.recruitment.description && <p>{my.recruitment.description}</p>}
            {my.application ? (
              <div className={`result ${my.assignment ? 'result--ok' : ''}`} data-testid="my-result" role="status">
                {my.assignment ? (
                  <>
                    <p className="result__big">
                      Вы в команде «{my.assignment.team}», роль — {my.assignment.role}
                    </p>
                    <p className="hint">Состав формирует организатор. Если что-то изменится, эта страница обновится сама.</p>
                  </>
                ) : (
                  <>
                    <p className="result__big">Ваша заявка в очереди</p>
                    <p className="hint">
                      {my.recruitment.status === 'open' ? 'Организатор ещё не назначил вас в команду. Страница обновляется сама.' : 'Набор закрыт, назначение не состоялось.'}
                    </p>
                  </>
                )}
              </div>
            ) : my.recruitment.status === 'closed' ? (
              <p>Набор закрыт, отклики не принимаются.</p>
            ) : null}
          </section>

          {my.application ? (
            <section className="card" aria-labelledby="my-card-heading">
              <h2 id="my-card-heading">Ваша карточка</h2>
              <p className="pcard__name">{my.application.name}</p>
              <p>Навыки: {my.application.skills.join(', ') || '—'}</p>
              <p>Интересы: {my.application.interests || '—'}</p>
              <p>Желаемые роли: {my.application.desired_roles.join(', ') || 'любая'}</p>
            </section>
          ) : (
            my.recruitment.status === 'open' && (
              <ApplicationForm
                my={my}
                defaultName={my.profile?.name ?? user.display_name}
                onDone={async () => {
                  await load();
                  announce('Отклик отправлен');
                }}
              />
            )
          )}
        </>
      )}
    </main>
  );
}

function ApplicationForm({ my, defaultName, onDone }: { my: MyStatus; defaultName: string; onDone: () => Promise<void> }) {
  const [name, setName] = useState(defaultName);
  const [skills, setSkills] = useState(my.profile?.skills.join(', ') ?? '');
  const [interests, setInterests] = useState(my.profile?.interests ?? '');
  const [roles, setRoles] = useState<string[]>([]);
  const [note, setNote] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const focusFirstError = (errs: Record<string, string>) => {
    const order = ['name', 'skills', 'interests', 'desired_roles', 'note'];
    const first = order.find((k) => errs[k]);
    if (first) formRef.current?.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus();
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseSkills(skills);
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = 'Введите имя';
    if (parsed.some((s) => s.length > 30)) errs.skills = 'Каждый навык — не длиннее 30 символов';
    if (parsed.length > 12) errs.skills = 'Не больше 12 навыков';
    if (interests.length > 300) errs.interests = 'Не длиннее 300 символов';
    setErrors(errs);
    if (Object.keys(errs).length) return focusFirstError(errs);
    setBusy(true);
    try {
      await api.apply(my.recruitment.id, { name: name.trim(), skills: parsed, interests: interests.trim(), desired_roles: roles, note: note.trim() });
      await onDone();
    } catch (err) {
      if (err instanceof ApiError) {
        const fe = Object.keys(err.fields).length ? err.fields : { form: err.message };
        setErrors(fe);
        focusFirstError(fe);
      } else setErrors({ form: 'Не удалось отправить' });
    } finally {
      setBusy(false);
    }
  };

  const fieldProps = (k: string) => ({
    'data-field': k,
    'aria-invalid': Boolean(errors[k]),
    'aria-describedby': errors[k] ? `e-${k}` : undefined,
  });
  const err = (k: string) =>
    errors[k] ? (
      <p id={`e-${k}`} className="error">
        {errors[k]}
      </p>
    ) : null;

  return (
    <section className="card" aria-labelledby="apply-heading">
      <h2 id="apply-heading">Откликнуться</h2>
      <form ref={formRef} onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="a-name">Имя на карточке</label>
          <input id="a-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} {...fieldProps('name')} />
          {err('name')}
        </div>
        <div className="field">
          <label htmlFor="a-skills">Навыки (через запятую)</label>
          <input id="a-skills" value={skills} onChange={(e) => setSkills(e.target.value)} placeholder="Python, SQL, Figma" {...fieldProps('skills')} />
          {err('skills')}
        </div>
        <div className="field">
          <label htmlFor="a-interests">Интересы</label>
          <textarea id="a-interests" rows={2} value={interests} onChange={(e) => setInterests(e.target.value)} {...fieldProps('interests')} />
          {err('interests')}
        </div>
        <fieldset className="roles" {...fieldProps('desired_roles')} tabIndex={-1}>
          <legend>Желаемые роли</legend>
          {my.roles.map((r) => (
            <label key={r} className="check">
              <input type="checkbox" checked={roles.includes(r)} onChange={(e) => setRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))} />
              {r}
            </label>
          ))}
          {my.roles.length === 0 && <p className="muted">Роли ещё не заданы — можно отправить без выбора.</p>}
        </fieldset>
        {err('desired_roles')}
        <div className="field">
          <label htmlFor="a-note">Комментарий для организатора</label>
          <input id="a-note" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} {...fieldProps('note')} />
          {err('note')}
        </div>
        {errors.form && (
          <p className="error" role="alert">
            {errors.form}
          </p>
        )}
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? 'Отправляем…' : 'Отправить отклик'}
        </button>
      </form>
    </section>
  );
}
