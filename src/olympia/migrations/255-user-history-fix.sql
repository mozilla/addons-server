ALTER TABLE users_history DROP KEY email;
CREATE INDEX users_history_email ON users_history (email);
