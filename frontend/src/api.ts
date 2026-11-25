/** Клиент API. Сессия — HttpOnly-cookie на том же адресе, поэтому токен в коде не хранится. */

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: 'organizer' | 'participant';
}

export interface Card {
  id: number;
  user_id: number;
  name: string;
  skills: string[];
  interests: string;
  desired_roles: string[];
  note: string;
  version: number;
  slot_id: number | null;
  created_at: string;
}

export interface Slot {
  id: number;
  role: string;
  capacity: number;
  taken: number;
  free: number;
  members: Card[];
}

export interface Team {
  id: number;
  name: string;
  slots: Slot[];
}

export interface Recruitment {
  id: number;
  title: string;
  description: string;
  status: 'open' | 'closed';
  board_version: number;
}

export interface Board {
  recruitment: Recruitment;
  board_version: number;
  teams: Team[];
  queue: Card[];
  summary: {
    capacity: number;
    filled: number;
    open_slots: Array<{ slot_id: number; team: string; role: string; free: number }>;
    applications: number;
    unassigned: number;
  };
  roles: string[];
  skills: string[];
}

export interface RecruitmentListItem extends Recruitment {
  applications: number;
  capacity: number;
  filled: number;
}

export interface MyStatus {
  recruitment: Recruitment;
  roles: string[];
  application: Card | null;
  assignment: { team: string; role: string } | null;
  profile: { name: string; skills: string[]; interests: string } | null;
}

export interface DemoUser {
  username: string;
  display_name: string;
  role: 'organizer' | 'participant';
  password: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field?: string,
    readonly board?: Board,
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

const FIELD_MESSAGES: Record<string, string> = {
  string_too_short: 'Поле не заполнено',
  string_too_long: 'Слишком длинно',
  greater_than_equal: 'Слишком маленькое значение',
  less_than_equal: 'Слишком большое значение',
  int_parsing: 'Нужно целое число',
  too_long: 'Слишком много значений',
};

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', 'Сервер недоступен. Проверьте, что контейнер запущен, и повторите.');
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const d = (data ?? {}) as Record<string, unknown>;
    // Сессия истекла или cookie удалены: приложение показывает вход (кроме самой попытки входа и проверки /me).
    if (res.status === 401 && url !== '/api/auth/login' && url !== '/api/me') {
      window.dispatchEvent(new CustomEvent('auth-lost'));
    }
    if (res.status === 422 && Array.isArray(d.detail)) {
      // Ошибки проверки FastAPI: [{loc: ['body', 'name'], msg, type}]
      const fields: Record<string, string> = {};
      for (const e of d.detail as Array<{ loc: Array<string | number>; msg: string; type: string }>) {
        const f = e.loc.filter((x): x is string => typeof x === 'string' && x !== 'body').pop() ?? '';
        fields[f] = FIELD_MESSAGES[e.type] ?? e.msg.replace(/^Value error, /, '');
      }
      throw new ApiError(422, 'validation', 'Проверьте выделенные поля', undefined, undefined, fields);
    }
    const field = typeof d.field === 'string' ? d.field : undefined;
    const message = typeof d.message === 'string' ? d.message : `Ошибка ${res.status}`;
    throw new ApiError(res.status, typeof d.code === 'string' ? d.code : 'error', message, field, d.board as Board | undefined, field ? { [field]: message } : {});
  }
  return data as T;
}

export const api = {
  me: () => request<{ user: User }>('GET', '/api/me'),
  login: (username: string, password: string) => request<{ user: User }>('POST', '/api/auth/login', { username, password }),
  logout: () => request<{ ok: boolean }>('POST', '/api/auth/logout'),
  demoUsers: () => request<{ users: DemoUser[] }>('GET', '/api/demo/users'),
  recruitments: () => request<{ recruitments: RecruitmentListItem[] }>('GET', '/api/recruitments'),
  createRecruitment: (title: string, description: string) => request<Board>('POST', '/api/recruitments', { title, description }),
  patchRecruitment: (id: number, patch: Partial<Pick<Recruitment, 'title' | 'description' | 'status'>>) => request<Board>('PATCH', `/api/recruitments/${id}`, patch),
  board: (id: number) => request<Board>('GET', `/api/recruitments/${id}/board`),
  my: (id: number) => request<MyStatus>('GET', `/api/recruitments/${id}/my`),
  apply: (id: number, body: { name: string; skills: string[]; interests: string; desired_roles: string[]; note: string }) =>
    request<{ application: Card }>('POST', `/api/recruitments/${id}/applications`, body),
  assign: (appId: number, slotId: number, version: number) =>
    request<{ changed: boolean; free_places: number; board: Board }>('PUT', `/api/applications/${appId}/assignment`, { slot_id: slotId, version }),
  unassign: (appId: number, version: number) => request<{ changed: boolean; board: Board }>('DELETE', `/api/applications/${appId}/assignment?version=${version}`),
  addTeam: (rid: number, name: string) => request<Board>('POST', `/api/recruitments/${rid}/teams`, { name }),
  deleteTeam: (teamId: number) => request<Board>('DELETE', `/api/teams/${teamId}`),
  addSlot: (teamId: number, role: string, capacity: number) => request<Board>('POST', `/api/teams/${teamId}/slots`, { role, capacity }),
  patchSlot: (slotId: number, capacity: number) => request<Board>('PATCH', `/api/slots/${slotId}`, { capacity }),
  deleteSlot: (slotId: number) => request<Board>('DELETE', `/api/slots/${slotId}`),
};
