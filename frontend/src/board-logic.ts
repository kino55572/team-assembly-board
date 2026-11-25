/** Чистые функции интерфейса доски — тестируются Vitest без браузера. */
import type { Board, Card, Slot } from './api';

export interface SlotRef {
  slot: Slot;
  team: string;
}

export function allSlots(board: Board): SlotRef[] {
  return board.teams.flatMap((t) => t.slots.map((slot) => ({ slot, team: t.name })));
}

export function findCard(board: Board, id: number): Card | null {
  for (const c of board.queue) if (c.id === id) return c;
  for (const t of board.teams) for (const s of t.slots) for (const m of s.members) if (m.id === id) return m;
  return null;
}

/** Фильтр очереди: все выбранные навыки должны быть у карточки, строка ищется в имени, навыках, интересах и ролях. */
export function filterQueue(queue: Card[], skills: string[], text: string): Card[] {
  const need = skills.map((s) => s.toLowerCase());
  const q = text.trim().toLowerCase();
  return queue.filter((c) => {
    const own = c.skills.map((s) => s.toLowerCase());
    if (!need.every((s) => own.includes(s))) return false;
    if (!q) return true;
    return [c.name, c.interests, ...c.skills, ...c.desired_roles].some((v) => v.toLowerCase().includes(q));
  });
}

/**
 * Варианты для меню «Назначить»: сначала слоты с желаемой ролью участника, затем остальные.
 * Заполненные слоты остаются в списке (видно, что места нет), но недоступны.
 */
export function slotOptions(board: Board, card: Card): Array<SlotRef & { desired: boolean; current: boolean; available: boolean }> {
  return allSlots(board)
    .map((r) => ({
      ...r,
      desired: card.desired_roles.includes(r.slot.role),
      current: card.slot_id === r.slot.id,
      available: card.slot_id === r.slot.id || r.slot.free > 0,
    }))
    .sort((a, b) => Number(b.desired) - Number(a.desired) || Number(b.available) - Number(a.available));
}

export function parseSkills(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[,;\n]/)) {
    const s = raw.trim();
    if (s && !out.some((x) => x.toLowerCase() === s.toLowerCase())) out.push(s);
  }
  return out;
}
