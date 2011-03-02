UPDATE translations
    SET localized_string=TRIM(localized_string)
    WHERE localized_string LIKE ' %' or localized_string LIKE '% ';
-- Query OK, 187318 rows affected (45.45 sec)
