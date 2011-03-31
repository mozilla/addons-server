ALTER TABLE perf_osversions ADD COLUMN name varchar(255);

UPDATE perf_osversions SET name='Mac OS X 10.5.8' WHERE id=1;
UPDATE perf_osversions SET name='Fedora 12' WHERE id=2;
UPDATE perf_osversions SET name='Windows XP' WHERE id=3;
UPDATE perf_osversions SET name='Windows 7' WHERE id=4;
