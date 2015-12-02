ALTER TABLE appsupport
  ADD CONSTRAINT UNIQUE (addon_id, app_id);
