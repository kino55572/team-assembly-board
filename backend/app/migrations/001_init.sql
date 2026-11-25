-- 001: исходная схема доски сборки команд.
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('organizer', 'participant')),
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL
);

CREATE TABLE sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

-- Профиль участника: имя, навыки и интересы, которые переносятся в карточку отклика.
CREATE TABLE profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  skills TEXT NOT NULL DEFAULT '[]',
  interests TEXT NOT NULL DEFAULT ''
);

CREATE TABLE recruitments (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('open', 'closed')) DEFAULT 'open',
  organizer_id INTEGER NOT NULL REFERENCES users(id),
  board_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE teams (
  id INTEGER PRIMARY KEY,
  recruitment_id INTEGER NOT NULL REFERENCES recruitments(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  UNIQUE (recruitment_id, name)
);

-- Слот роли: роль в команде и её вместимость.
CREATE TABLE role_slots (
  id INTEGER PRIMARY KEY,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  capacity INTEGER NOT NULL CHECK (capacity >= 1 AND capacity <= 50),
  position INTEGER NOT NULL DEFAULT 0,
  UNIQUE (team_id, role)
);

-- Отклик участника на набор: один на человека в наборе.
CREATE TABLE applications (
  id INTEGER PRIMARY KEY,
  recruitment_id INTEGER NOT NULL REFERENCES recruitments(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  desired_roles TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  assignment_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE (recruitment_id, user_id)
);

-- Назначение связывает отклик со слотом. Первичный ключ по отклику: человек занимает не больше одного места.
CREATE TABLE assignments (
  application_id INTEGER PRIMARY KEY REFERENCES applications(id) ON DELETE CASCADE,
  slot_id INTEGER NOT NULL REFERENCES role_slots(id),
  assigned_by INTEGER NOT NULL REFERENCES users(id),
  assigned_at TEXT NOT NULL
);

CREATE INDEX ix_assignments_slot ON assignments(slot_id);
CREATE INDEX ix_applications_recruitment ON applications(recruitment_id);
CREATE INDEX ix_teams_recruitment ON teams(recruitment_id);
CREATE INDEX ix_slots_team ON role_slots(team_id);
