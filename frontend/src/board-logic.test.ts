import { describe, expect, it } from 'vitest';
import type { Board, Card } from './api';
import { filterQueue, findCard, parseSkills, slotOptions } from './board-logic';

const card = (id: number, name: string, skills: string[], roles: string[], slot: number | null = null): Card => ({
  id,
  user_id: id,
  name,
  skills,
  interests: 'мобильные приложения',
  desired_roles: roles,
  note: '',
  version: 0,
  slot_id: slot,
  created_at: '',
});

const a = card(1, 'Антон', ['Python', 'SQL'], ['Backend']);
const b = card(2, 'Вика', ['React', 'TypeScript'], ['Frontend']);
const c = card(3, 'Денис', ['Figma'], ['Дизайн'], 13);

const board: Board = {
  recruitment: { id: 1, title: 'X', description: '', status: 'open', board_version: 1 },
  board_version: 1,
  teams: [
    {
      id: 1,
      name: 'Альфа',
      slots: [
        { id: 11, role: 'Backend', capacity: 1, taken: 0, free: 1, members: [] },
        { id: 12, role: 'Frontend', capacity: 1, taken: 1, free: 0, members: [card(9, 'Занят', [], [], 12)] },
        { id: 13, role: 'Дизайн', capacity: 1, taken: 1, free: 0, members: [c] },
      ],
    },
  ],
  queue: [a, b],
  summary: { capacity: 3, filled: 2, open_slots: [], applications: 4, unassigned: 2 },
  roles: ['Backend', 'Frontend', 'Дизайн'],
  skills: ['Figma', 'Python', 'React', 'SQL', 'TypeScript'],
};

describe('filterQueue', () => {
  it('все выбранные навыки без учёта регистра и поиск по тексту', () => {
    expect(filterQueue([a, b], ['python'], '')).toEqual([a]);
    expect(filterQueue([a, b], ['Python', 'React'], '')).toEqual([]);
    expect(filterQueue([a, b], [], 'front')).toEqual([b]);
    expect(filterQueue([a, b], [], 'МОБИЛЬН')).toEqual([a, b]);
  });
});

describe('slotOptions', () => {
  it('желаемые роли первыми, занятые недоступны, текущий слот отмечен', () => {
    const opts = slotOptions(board, b);
    expect(opts[0]).toMatchObject({ desired: true, available: false });
    expect(opts.find((o) => o.slot.id === 11)?.available).toBe(true);
    const own = slotOptions(board, c).find((o) => o.slot.id === 13);
    expect(own).toMatchObject({ current: true, available: true });
  });
});

describe('прочее', () => {
  it('findCard ищет в очереди и в слотах; parseSkills убирает пустые и дубли', () => {
    expect(findCard(board, 3)?.name).toBe('Денис');
    expect(findCard(board, 42)).toBeNull();
    expect(parseSkills('Python, python; SQL\n , Go')).toEqual(['Python', 'SQL', 'Go']);
  });
});
