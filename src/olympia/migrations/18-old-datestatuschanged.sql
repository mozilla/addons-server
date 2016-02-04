UPDATE files
SET modified=created, datestatuschanged=created
WHERE datestatuschanged IS NULL AND STATUS=4;
