CREATE TABLE `l10n_settings` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `created` datetime NOT NULL,
      `modified` datetime NOT NULL,
      `locale` varchar(30) NOT NULL,
      `motd` int(11) DEFAULT NULL,
      `team_homepage` varchar(255) DEFAULT NULL,
      PRIMARY KEY (`id`),
      UNIQUE KEY `locale` (`locale`),
      UNIQUE KEY `motd` (`motd`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8 ;

INSERT INTO l10n_settings (locale, team_homepage) VALUES
    ('ca', 'http://www.mozilla.cat/'),
    ('cs', 'http://www.mozilla.cz/'),
    ('da', 'http://mozilladanmark.dk/'),
    ('es-ES', 'http://www.proyectonave.es/'),
    ('eu', 'http://www.librezale.org/'),
    ('fy-NL', 'http://www.mozilla-nl.org/projecten/frysk'),
    ('fr', 'http://www.frenchmozilla.fr/'),
    ('ga-IE', 'http://gaeilge.mozdev.org/'),
    ('he', 'http://mozilla.org.il/'),
    ('hu', 'http://mozilla.fsf.hu/'),
    ('it', 'http://www.mozillaitalia.it/'),
    ('lt', 'http://firefox.lt/'),
    ('nl', 'http://www.mozilla-nl.org'),
    ('pl', 'http://www.aviary.pl/'),
    ('pt-PT', 'http://mozilla.pt/'),
    ('si', 'http://www.mozilla.lk/'),
    ('sk', 'http://www.mozilla.sk/'),
    ('ta-LK', 'http://www.mozilla.lk/'),
    ('uk', 'http://mozilla.org.ua/'),
    ('vi', 'http://vi.mozdev.org/'),
    ('zh-CN', 'http://narro.mozest.com/'),
    ('zh-TW', 'http://moztw.org/')
;
UPDATE l10n_settings SET created=NOW(), modified=NOW();
