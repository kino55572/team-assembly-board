import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Board } from '../api';

interface Props {
  board: Board | null;
  onBoard: (b: Board) => void;
  onCreated: (b: Board) => void | Promise<void>;
  announce: (t: string) => void;
}

/** Настройка набора: открыть/закрыть, команды, роли и вместимость, новый набор. */
export function SetupPanel({ board, onBoard, onCreated, announce }: Props) {
  const [teamName, setTeamName] = useState('');
  const [roleDraft, setRoleDraft] = useState<Record<number, { role: string; capacity: string }>>({});
  const [capDraft, setCapDraft] = useState<Record<number, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [newTitle, setNewTitle] = useState('');
  // Панель открыта, пока пользователь её не свернул. Сама раскрывается для набора без команд.
  const [open, setOpen] = useState(false);
  const autoOpenedFor = useRef<number | null>(null);
  useEffect(() => {
    if (board && board.teams.length === 0 && autoOpenedFor.current !== board.recruitment.id) {
      autoOpenedFor.current = board.recruitment.id;
      setOpen(true);
    }
  }, [board]);

  const run = async (key: string, fn: () => Promise<Board>, ok: string) => {
    try {
      const b = await fn();
      setErrors((e) => ({ ...e, [key]: '' }));
      onBoard(b);
      announce(ok);
      return true;
    } catch (e) {
      const msg = e instanceof ApiError ? Object.values(e.fields)[0] ?? e.message : 'Ошибка';
      setErrors((x) => ({ ...x, [key]: msg }));
      return false;
    }
  };

  return (
    <details className="card setup" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <h2>Настройка набора</h2>
      </summary>
      {board && (
        <>
          <div className="setup__row">
            <span>
              Статус: <strong>{board.recruitment.status === 'open' ? 'открыт — принимаются отклики, состав меняется' : 'закрыт — состав зафиксирован'}</strong>
            </span>
            <button
              type="button"
              className="btn btn--sm"
              onClick={() =>
                void run(
                  'status',
                  () => api.patchRecruitment(board.recruitment.id, { status: board.recruitment.status === 'open' ? 'closed' : 'open' }),
                  board.recruitment.status === 'open' ? 'Набор закрыт' : 'Набор открыт',
                )
              }
            >
              {board.recruitment.status === 'open' ? 'Закрыть набор' : 'Открыть набор'}
            </button>
          </div>

          {board.teams.map((t) => {
            const d = roleDraft[t.id] ?? { role: '', capacity: '1' };
            const key = `slot-${t.id}`;
            return (
              <fieldset key={t.id} className="setup__team">
                <legend>Команда «{t.name}»</legend>
                <ul className="setup__slots">
                  {t.slots.map((s) => {
                    const ck = `cap-${s.id}`;
                    return (
                      <li key={s.id}>
                        <span className="setup__role">{s.role}</span>
                        <label htmlFor={ck} className="sr-only">
                          Вместимость роли {s.role} в команде {t.name}
                        </label>
                        <input
                          id={ck}
                          className="num"
                          inputMode="numeric"
                          value={capDraft[s.id] ?? String(s.capacity)}
                          aria-invalid={Boolean(errors[ck])}
                          aria-describedby={errors[ck] ? `${ck}-e` : undefined}
                          onChange={(e) => setCapDraft({ ...capDraft, [s.id]: e.target.value })}
                        />
                        <button
                          type="button"
                          className="btn btn--sm"
                          onClick={() => void run(ck, () => api.patchSlot(s.id, Number(capDraft[s.id] ?? s.capacity)), `Вместимость роли ${s.role} обновлена`)}
                        >
                          Сохранить
                        </button>
                        <button type="button" className="btn btn--sm btn--ghost" onClick={() => void run(ck, () => api.deleteSlot(s.id), `Роль ${s.role} удалена`)}>
                          Удалить роль
                        </button>
                        {errors[ck] && (
                          <span id={`${ck}-e`} className="error">
                            {errors[ck]}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
                <form
                  className="setup__add"
                  noValidate
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (!d.role.trim()) return setErrors({ ...errors, [key]: 'Введите роль' });
                    if (await run(key, () => api.addSlot(t.id, d.role.trim(), Number(d.capacity)), `Роль ${d.role.trim()} добавлена в «${t.name}»`)) {
                      setRoleDraft({ ...roleDraft, [t.id]: { role: '', capacity: '1' } });
                    }
                  }}
                >
                  <div className="field">
                    <label htmlFor={`${key}-role`}>Новая роль</label>
                    <input
                      id={`${key}-role`}
                      value={d.role}
                      aria-invalid={Boolean(errors[key])}
                      aria-describedby={errors[key] ? `${key}-e` : undefined}
                      onChange={(e) => setRoleDraft({ ...roleDraft, [t.id]: { ...d, role: e.target.value } })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`${key}-cap`}>Мест</label>
                    <input id={`${key}-cap`} className="num" inputMode="numeric" value={d.capacity} onChange={(e) => setRoleDraft({ ...roleDraft, [t.id]: { ...d, capacity: e.target.value } })} />
                  </div>
                  <button type="submit" className="btn btn--sm">
                    Добавить роль
                  </button>
                  <button type="button" className="btn btn--sm btn--ghost" onClick={() => void run(key, () => api.deleteTeam(t.id), `Команда «${t.name}» удалена`)}>
                    Удалить команду
                  </button>
                  {errors[key] && (
                    <p id={`${key}-e`} className="error">
                      {errors[key]}
                    </p>
                  )}
                </form>
              </fieldset>
            );
          })}

          <form
            className="setup__add"
            noValidate
            onSubmit={async (e) => {
              e.preventDefault();
              if (!teamName.trim()) return setErrors({ ...errors, team: 'Введите название команды' });
              if (await run('team', () => api.addTeam(board.recruitment.id, teamName.trim()), `Команда «${teamName.trim()}» добавлена`)) setTeamName('');
            }}
          >
            <div className="field">
              <label htmlFor="new-team">Новая команда</label>
              <input id="new-team" value={teamName} aria-invalid={Boolean(errors.team)} aria-describedby={errors.team ? 'new-team-e' : undefined} onChange={(e) => setTeamName(e.target.value)} />
            </div>
            <button type="submit" className="btn btn--sm">
              Добавить команду
            </button>
            {errors.team && (
              <p id="new-team-e" className="error">
                {errors.team}
              </p>
            )}
          </form>
          {errors.status && <p className="error">{errors.status}</p>}
        </>
      )}

      <form
        className="setup__add setup__new"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault();
          if (!newTitle.trim()) return setErrors({ ...errors, rec: 'Введите название набора' });
          try {
            const b = await api.createRecruitment(newTitle.trim(), '');
            setNewTitle('');
            setErrors({ ...errors, rec: '' });
            await onCreated(b);
          } catch (err) {
            setErrors({ ...errors, rec: err instanceof ApiError ? err.message : 'Ошибка' });
          }
        }}
      >
        <div className="field">
          <label htmlFor="new-rec">Открыть новый набор</label>
          <input id="new-rec" value={newTitle} aria-invalid={Boolean(errors.rec)} aria-describedby={errors.rec ? 'new-rec-e' : undefined} onChange={(e) => setNewTitle(e.target.value)} placeholder="Например, весенний интенсив" />
        </div>
        <button type="submit" className="btn btn--sm">
          Создать набор
        </button>
        {errors.rec && (
          <p id="new-rec-e" className="error">
            {errors.rec}
          </p>
        )}
      </form>
    </details>
  );
}
