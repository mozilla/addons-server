ALTER TABLE prices DROP FOREIGN KEY name_translated;
ALTER TABLE prices CHANGE name name varchar(4) NOT NULL default '';
