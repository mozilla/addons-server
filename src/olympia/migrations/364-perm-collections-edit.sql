UPDATE groups SET rules=CONCAT(rules, ',Collections:Edit') WHERE groups.name='Staff' AND id >= 50000;
