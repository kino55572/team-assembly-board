import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, type Board, type Card, type RecruitmentListItem } from '../api';
import { filterQueue } from '../board-logic';
import { AssignDialog } from './AssignDialog';
import { CardView } from './CardView';
import { SetupPanel } from './SetupPanel';

const POLL_MS = 5000;
const LAST = 'tab.lastRecruitment';

export function OrganizerView({ announce }: { announce: (t: string) => void }) {
  const [list, setList] = useState<RecruitmentListItem[]>([]);
  const [rid, setRid] = useState<number | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [busyCard, setBusyCard] = useState<number | null>(null);
  const [skills, setSkills] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [dialogCard, setDialogCard] = useState<Card | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [dropSlot, setDropSlot] = useState<number | null>(null);
  const focusCardRef = useRef<number | null>(null);
  const versionRef = useRef<number>(-1);

  const applyBoard = useCallback((b: Board) => {
    versionRef.current = b.board_version;
    setBoard(b);
  }, []);

  const loadList = useCallback(async () => {
    const r = await api.recruitments();
    setList(r.recruitments);
    return r.recruitments;
  }, []);

  useEffect(() => {
    void loadList()
      .then((items) => {
        const last = Number(localStorage.getItem(LAST));
        setRid(items.find((i) => i.id === last)?.id ?? items[0]?.id ?? null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить наборы'));
  }, [loadList]);

  const refresh = useCallback(
    async (quiet = false) => {
      if (rid === null) return;
      try {
        const b = await api.board(rid);
        if (b.board_version !== versionRef.current) applyBoard(b);
        setError(null);
      } catch (e) {
        if (!quiet) setError(e instanceof ApiError ? e.message : 'Не удалось загрузить доску');
      }
    },
    [rid, applyBoard],
  );

  useEffect(() => {
    if (rid === null) return;
    try {
      localStorage.setItem(LAST, String(rid));
    } catch {
      /* не критично */
    }
    versionRef.current = -1;
    setBoard(null);
    void refresh();
  }, [rid, refresh]);

  // Доска обновляется, пока вкладка видна: изменения других организаторов и новые отклики.
  useEffect(() => {
    if (rid === null) return undefined;
    const tick = () => {
      if (document.visibilityState === 'visible') void refresh(true);
    };
    const h = setInterval(tick, POLL_MS);
    window.addEventListener('focus', tick);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(h);
      window.removeEventListener('focus', tick);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [rid, refresh]);

  // После назначения через меню фокус следует за карточкой на её новое место.
  useEffect(() => {
    const id = focusCardRef.current;
    if (id === null) return;
    focusCardRef.current = null;
    document.querySelector<HTMLElement>(`[data-card-id="${id}"] [data-card-main]`)?.focus();
  }, [board]);

  /** Если фокус всё же потерян (например, карточка перерисована), после отрисовки возвращаем его на карточку. */
  const pendingFocusRef = useRef<number | null>(null);
  const restoreFocus = (id: number) => {
    pendingFocusRef.current = id;
  };
  useEffect(() => {
    const id = pendingFocusRef.current;
    if (id === null || busyCard !== null) return;
    pendingFocusRef.current = null;
    const active = document.activeElement;
    if (active && active !== document.body) return;
    document.querySelector<HTMLElement>(`[data-card-id="${id}"] [data-card-main]`)?.focus();
  }, [busyCard, board]);

  const handleError = (e: unknown, fallback: string) => {
    if (e instanceof ApiError && e.board) {
      applyBoard(e.board);
      setConflict(e.message);
      announce(`Конфликт: ${e.message}`);
    } else {
      setError(e instanceof ApiError ? e.message : fallback);
    }
  };

  const assign = async (card: Card, slotId: number, viaMenu: boolean) => {
    if (!board) return;
    const target = board.teams.flatMap((t) => t.slots.map((s) => ({ s, team: t.name }))).find((x) => x.s.id === slotId);
    setBusyCard(card.id);
    setConflict(null);
    try {
      const r = await api.assign(card.id, slotId, card.version);
      if (viaMenu) focusCardRef.current = card.id;
      applyBoard(r.board);
      if (target) announce(`${card.name} → ${target.team}, ${target.s.role}. Свободных мест в роли: ${r.free_places}`);
      void loadList();
    } catch (e) {
      handleError(e, 'Не удалось назначить');
    } finally {
      setBusyCard(null);
      if (viaMenu) restoreFocus(card.id);
    }
  };

  const unassign = async (card: Card) => {
    setBusyCard(card.id);
    setConflict(null);
    try {
      const r = await api.unassign(card.id, card.version);
      focusCardRef.current = card.id;
      applyBoard(r.board);
      announce(`${card.name} возвращён в очередь`);
      void loadList();
    } catch (e) {
      handleError(e, 'Не удалось вернуть в очередь');
    } finally {
      setBusyCard(null);
      restoreFocus(card.id);
    }
  };

  const queue = useMemo(() => (board ? filterQueue(board.queue, skills, text) : []), [board, skills, text]);
  const closed = board?.recruitment.status === 'closed';

  const onDrop = (slotId: number) => {
    const id = dragId;
    setDragId(null);
    setDropSlot(null);
    if (!board || id === null) return;
    const all = [...board.queue, ...board.teams.flatMap((t) => t.slots.flatMap((s) => s.members))];
    const card = all.find((c) => c.id === id);
    if (card && card.slot_id !== slotId) void assign(card, slotId, false);
  };

  return (
    <main className="organizer">
      <div className="bar">
        <div className="field field--inline">
          <label htmlFor="rec-select">Набор</label>
          <select id="rec-select" value={rid ?? ''} onChange={(e) => setRid(Number(e.target.value))}>
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title} — {r.filled}/{r.capacity} мест, откликов {r.applications}
                {r.status === 'closed' ? ' (закрыт)' : ''}
              </option>
            ))}
          </select>
        </div>
        <div className="bar__actions">
          <button type="button" className="btn btn--sm" onClick={() => void refresh()}>
            Обновить
          </button>
          {board && (
            <a className="btn btn--sm" href={`/api/recruitments/${board.recruitment.id}/export.csv`} download>
              Экспорт состава CSV
            </a>
          )}
        </div>
      </div>

      {error && (
        <p className="banner banner--err" role="alert">
          {error}{' '}
          <button type="button" className="btn btn--sm" onClick={() => void refresh()}>
            Повторить
          </button>
        </p>
      )}
      {conflict && (
        <p className="banner banner--warn" role="alert" data-testid="conflict">
          {conflict} Показано актуальное состояние доски.{' '}
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => setConflict(null)}>
            Понятно
          </button>
        </p>
      )}

      {!board ? (
        rid === null ? (
          <p className="muted">Наборов пока нет — создайте первый в настройке ниже.</p>
        ) : (
          <p className="muted">Загрузка доски…</p>
        )
      ) : (
        <>
          <section className="summary card" aria-labelledby="summary-heading">
            <h1 id="summary-heading">
              {board.recruitment.title} <span className={`status status--${board.recruitment.status}`}>{closed ? 'набор закрыт' : 'набор открыт'}</span>
            </h1>
            <p data-testid="summary-filled">
              Заполнено мест: <strong>{board.summary.filled}</strong> из <strong>{board.summary.capacity}</strong> · в очереди: <strong>{board.summary.unassigned}</strong>
            </p>
            {board.summary.open_slots.length === 0 ? (
              <p className="ok-line" data-testid="open-roles">
                Все роли закрыты.
              </p>
            ) : (
              <p data-testid="open-roles">
                Незакрытые роли:{' '}
                {board.summary.open_slots.map((o) => (
                  <span key={o.slot_id} className="chip chip--open">
                    {o.team} — {o.role}
                    {o.free > 1 ? ` ×${o.free}` : ''}
                    
                  </span>
                ))}
              </p>
            )}
            {closed && <p className="hint">Набор закрыт: состав зафиксирован. Откройте набор в настройке, чтобы менять назначения.</p>}
          </section>

          <div className="board">
            <section className="column column--queue" aria-labelledby="queue-heading">
              <h2 id="queue-heading">
                Очередь <span className="count">{board.queue.length}</span>
              </h2>
              <div className="filters">
                <div className="field">
                  <label htmlFor="q-text">Поиск</label>
                  <input id="q-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="имя, навык, роль" />
                </div>
                {board.skills.length > 0 && (
                  <fieldset className="skills">
                    <legend>Навыки</legend>
                    {board.skills.map((s) => (
                      <label key={s} className={`chip chip--toggle ${skills.includes(s) ? 'chip--on' : ''}`}>
                        <input type="checkbox" checked={skills.includes(s)} onChange={(e) => setSkills(e.target.checked ? [...skills, s] : skills.filter((x) => x !== s))} />
                        {s}
                      </label>
                    ))}
                  </fieldset>
                )}
                {(skills.length > 0 || text) && (
                  <p className="hint">
                    Показано {queue.length} из {board.queue.length}.{' '}
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      onClick={() => {
                        setSkills([]);
                        setText('');
                      }}
                    >
                      Сбросить фильтр
                    </button>
                  </p>
                )}
              </div>
              <ul className="cards" data-testid="queue">
                {queue.map((c) => (
                  <CardView
                    key={c.id}
                    card={c}
                    busy={busyCard === c.id}
                    disabled={closed}
                    onAssign={() => setDialogCard(c)}
                    onDragStart={() => setDragId(c.id)}
                    onDragEnd={() => setDragId(null)}
                  />
                ))}
                {queue.length === 0 && <li className="muted empty">{board.queue.length === 0 ? 'Все участники распределены.' : 'Никто не подходит под фильтр.'}</li>}
              </ul>
            </section>

            {board.teams.map((t) => {
              const taken = t.slots.reduce((s, x) => s + x.taken, 0);
              const cap = t.slots.reduce((s, x) => s + x.capacity, 0);
              return (
                <section key={t.id} className="column" aria-labelledby={`team-${t.id}`} data-testid="team" data-team={t.name}>
                  <h2 id={`team-${t.id}`}>
                    {t.name}{' '}
                    <span className="count">
                      {taken}/{cap}
                    </span>
                  </h2>
                  {t.slots.map((s) => (
                    <div
                      key={s.id}
                      className={`slot ${s.free === 0 ? 'slot--full' : ''} ${dropSlot === s.id ? 'slot--drop' : ''}`}
                      data-testid="slot"
                      data-slot={`${t.name}/${s.role}`}
                      onDragOver={(e) => {
                        if (dragId !== null && !closed) {
                          e.preventDefault();
                          setDropSlot(s.id);
                        }
                      }}
                      onDragLeave={() => setDropSlot((cur) => (cur === s.id ? null : cur))}
                      onDrop={(e) => {
                        e.preventDefault();
                        onDrop(s.id);
                      }}
                    >
                      <h3 className="slot__head">
                        <span>{s.role}</span>
                        <span className={`slot__count ${s.free > 0 ? 'slot__count--open' : ''}`} aria-label={`занято ${s.taken} из ${s.capacity}`}>
                          {s.taken}/{s.capacity}
                        </span>
                      </h3>
                      <ul className="cards">
                        {s.members.map((m) => (
                          <CardView
                            key={m.id}
                            card={m}
                            busy={busyCard === m.id}
                            disabled={closed}
                            placed
                            onAssign={() => setDialogCard(m)}
                            onUnassign={() => void unassign(m)}
                            onDragStart={() => setDragId(m.id)}
                            onDragEnd={() => setDragId(null)}
                          />
                        ))}
                        {Array.from({ length: s.free }, (_, i) => (
                          <li key={`free-${i}`} className="placeholder">
                            свободно
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {t.slots.length === 0 && <p className="muted">Ролей нет — добавьте в настройке.</p>}
                </section>
              );
            })}
          </div>
        </>
      )}

      <SetupPanel
        board={board}
        onBoard={(b) => {
          applyBoard(b);
          void loadList();
        }}
        onCreated={async (b) => {
          applyBoard(b);
          await loadList();
          setRid(b.recruitment.id);
          announce(`Набор «${b.recruitment.title}» создан`);
        }}
        announce={announce}
      />

      {dialogCard && board && (
        <AssignDialog
          board={board}
          card={dialogCard}
          onClose={() => setDialogCard(null)}
          onPick={(slotId) => {
            const c = dialogCard;
            setDialogCard(null);
            void assign(c, slotId, true);
          }}
          onUnassign={() => {
            const c = dialogCard;
            setDialogCard(null);
            void unassign(c);
          }}
        />
      )}
    </main>
  );
}
