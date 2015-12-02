UPDATE translations
    SET localized_string=TRIM(localized_string)
    WHERE
        localized_string LIKE ' %' AND
        id IN (SELECT name FROM addons);
