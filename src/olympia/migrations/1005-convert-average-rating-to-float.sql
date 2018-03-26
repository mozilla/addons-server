-- Before converting to a double, get rid of the empty string values we can't
-- convert.
UPDATE users SET averagerating=NULL WHERE averagerating = "";
-- Make it a double.
ALTER TABLE users MODIFY averagerating double;
