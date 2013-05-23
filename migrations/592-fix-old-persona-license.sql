-- This should've been fixed in migration 555. I don't even know ...

-- Creative Commons Attribution-Noncommercial-Share Alike 3.0
update personas set license = 5 where license = 8;
