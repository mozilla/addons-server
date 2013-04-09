INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (NULL, 'Payment transactions clients', 'Transaction:NotifyFailure',
   'Clients that can notify of failures in payments', NOW(), NOW());
