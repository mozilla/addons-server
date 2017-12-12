INSERT INTO waffle_switch (name, active, created, modified, note) VALUES ('activate-django-post-request', 0, NOW(), NOW(), 'Activate django-post-request-task') ON DUPLICATE KEY UPDATE active = 0;
