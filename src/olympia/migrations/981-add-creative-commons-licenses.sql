ALTER TABLE licenses
    ADD COLUMN `creative_commons` bool NOT NULL DEFAULT false;

/* See constants/licenses.py for names for these licenses. */
INSERT INTO `licenses`
    (`name`, `builtin`, `on_form`, `creative_commons`, `some_rights`, `icons`,
        `url`, `created`, `modified`)
VALUES
    (NULL, 11, true, true, true, 'copyr',
        NULL, NOW(), NOW()),                                                 /* LICENSE_COPYRIGHT */
    (NULL, 12, true, true, false, 'cc-attrib',
        'http://creativecommons.org/licenses/by/3.0/', NOW(), NOW()),        /* LICENSE_CC_BY */
    (NULL, 13, true, true, false, 'cc-attrib cc-noncom',
        'http://creativecommons.org/licenses/by-nc/3.0/', NOW(), NOW()),     /* LICENSE_CC_BY_NC */
    (NULL, 14, true, true, false, 'cc-attrib cc-noncom cc-noderiv',
        'http://creativecommons.org/licenses/by-nc-nd/3.0/', NOW(), NOW()),  /* LICENSE_CC_BY_NC_ND */
    (NULL, 15, true, true, false, 'cc-attrib cc-noncom cc-share',
        'http://creativecommons.org/licenses/by-nc-sa/3.0/', NOW(), NOW()),  /* LICENSE_CC_BY_NC_SA */
    (NULL, 16, true, true, false, 'cc-attrib cc-noderiv',
        'http://creativecommons.org/licenses/by-nd/3.0/', NOW(), NOW()),     /* LICENSE_CC_BY_ND */
    (NULL, 17, true, true, false, 'cc-attrib cc-share',
        'http://creativecommons.org/licenses/by-sa/3.0/', NOW(), NOW())      /* LICENSE_CC_BY_SA */
;
