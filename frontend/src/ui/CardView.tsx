import type { Card } from '../api';

interface Props {
  card: Card;
  busy: boolean;
  disabled: boolean;
  placed?: boolean;
  onAssign: () => void;
  onUnassign?: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
}

/** Карточка участника. Перетаскивание — для мыши, кнопки «Назначить/Перенести» и «В очередь» — для клавиатуры. */
export function CardView({ card, busy, disabled, placed, onAssign, onUnassign, onDragStart, onDragEnd }: Props) {
  return (
    <li
      className={`pcard ${busy ? 'pcard--busy' : ''}`}
      data-testid="card"
      data-card-id={card.id}
      data-name={card.name}
      draggable={!disabled && !busy}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', String(card.id));
        e.dataTransfer.effectAllowed = 'move';
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      aria-busy={busy}
    >
      <p className="pcard__name">{card.name}</p>
      {card.skills.length > 0 && (
        <ul className="tags" aria-label="Навыки">
          {card.skills.map((s) => (
            <li key={s} className="tag">
              {s}
            </li>
          ))}
        </ul>
      )}
      {card.desired_roles.length > 0 && <p className="pcard__roles">Хочет: {card.desired_roles.join(', ')}</p>}
      {card.interests && <p className="pcard__interests">{card.interests}</p>}
      {!disabled && (
        <div className="pcard__actions">
          {/* aria-disabled вместо disabled: кнопка не теряет фокус, пока идёт запрос */}
          <button
            type="button"
            className="btn btn--sm"
            data-card-main
            onClick={() => !busy && onAssign()}
            aria-disabled={busy}
            aria-label={`${placed ? 'Перенести' : 'Назначить'}: ${card.name}`}
          >
            {placed ? 'Перенести…' : 'Назначить…'}
          </button>
          {placed && onUnassign && (
            <button type="button" className="btn btn--sm btn--ghost" onClick={() => !busy && onUnassign()} aria-disabled={busy} aria-label={`В очередь: ${card.name}`}>
              В очередь
            </button>
          )}
        </div>
      )}
    </li>
  );
}
