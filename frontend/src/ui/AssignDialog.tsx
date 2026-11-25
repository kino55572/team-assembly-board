import { useEffect, useRef, useState } from 'react';
import type { Board, Card } from '../api';
import { slotOptions } from '../board-logic';

interface Props {
  board: Board;
  card: Card;
  onPick: (slotId: number) => void;
  onUnassign: () => void;
  onClose: () => void;
}

/** Меню назначения на <dialog>: список слотов радиокнопками. Сначала роли, которые хочет участник. */
export function AssignDialog({ board, card, onPick, onUnassign, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const opts = slotOptions(board, card);
  const [choice, setChoice] = useState<number | null>(() => opts.find((o) => o.available && !o.current)?.slot.id ?? null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    returnTo.current = document.activeElement as HTMLElement | null;
    const d = ref.current;
    if (d && !d.open) d.showModal();
    (d?.querySelector<HTMLInputElement>('input[type=radio]:checked') ?? firstRef.current)?.focus();
    return () => {
      d?.close();
      const back = returnTo.current;
      // Если карточка не переехала (отмена), возвращаем фокус на кнопку, открывшую меню.
      requestAnimationFrame(() => {
        if (back && back.isConnected && document.activeElement === document.body) back.focus();
      });
    };
  }, []);

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="assign-title" onCancel={onClose}>
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (choice !== null) onPick(choice);
        }}
      >
        <h2 id="assign-title">{card.slot_id === null ? 'Назначить' : 'Перенести'}: {card.name}</h2>
        {card.desired_roles.length > 0 && <p className="hint">Хочет: {card.desired_roles.join(', ')}</p>}
        <fieldset className="slot-options">
          <legend>Команда и роль</legend>
          {opts.map((o, i) => (
            <label key={o.slot.id} className={`slot-option ${o.available ? '' : 'slot-option--full'}`}>
              <input
                ref={i === 0 ? firstRef : undefined}
                type="radio"
                name="slot"
                value={o.slot.id}
                checked={choice === o.slot.id}
                disabled={!o.available || o.current}
                onChange={() => setChoice(o.slot.id)}
              />
              <span>
                {o.team} — {o.slot.role}
                {o.desired && <span className="tag tag--want"> хочет</span>}
              </span>
              <span className="muted">{o.current ? 'сейчас здесь' : o.available ? `свободно ${o.slot.free}` : 'занято'}</span>
            </label>
          ))}
        </fieldset>
        <div className="dialog__actions">
          <button type="submit" className="btn btn--primary" disabled={choice === null}>
            {card.slot_id === null ? 'Назначить' : 'Перенести'}
          </button>
          {card.slot_id !== null && (
            <button type="button" className="btn" onClick={onUnassign}>
              Вернуть в очередь
            </button>
          )}
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </dialog>
  );
}
