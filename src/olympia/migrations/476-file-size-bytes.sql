-- Assumption: Since we didn't care about byte precision before, we can do this:
UPDATE files SET size=size*1024;
