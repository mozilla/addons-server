ALTER TABLE categories
  ADD COLUMN `slug` varchar(50) NOT NULL default '';
CREATE INDEX `categories_slug` ON `categories` (`slug`);

-- "Feeds, News & Blogging" for Firefox (Extensions)
UPDATE categories SET slug="feeds-news-blogging" WHERE id=1;

-- "Web Development" for Firefox (Extensions)
UPDATE categories SET slug="web-development" WHERE id=4;

-- "Download Management" for Firefox (Extensions)
UPDATE categories SET slug="download-management" WHERE id=5;

-- "Privacy & Security" for Firefox (Extensions)
UPDATE categories SET slug="privacy-security" WHERE id=12;

-- "Search Tools" for Firefox (Extensions)
UPDATE categories SET slug="search-tools" WHERE id=13;

-- "Appearance" for Firefox (Extensions)
UPDATE categories SET slug="appearance" WHERE id=14;

-- "Miscellaneous" for Firefox (Themes)
UPDATE categories SET slug="miscellaneous" WHERE id=21;

-- "Bookmarks" for Firefox (Extensions)
UPDATE categories SET slug="bookmarks" WHERE id=22;

-- "Contacts" for Thunderbird (Extensions)
UPDATE categories SET slug="contacts" WHERE id=23;

-- "Sports" for Firefox (Themes)
UPDATE categories SET slug="sports" WHERE id=26;

-- "Nature" for Firefox (Themes)
UPDATE categories SET slug="nature" WHERE id=29;

-- "Animals" for Firefox (Themes)
UPDATE categories SET slug="animals" WHERE id=30;

-- "Retro" for Firefox (Themes)
UPDATE categories SET slug="retro" WHERE id=31;

-- "Compact" for Firefox (Themes)
UPDATE categories SET slug="compact" WHERE id=32;

-- "Language Support" for Firefox (Extensions)
UPDATE categories SET slug="language-support" WHERE id=37;

-- "Photos, Music & Videos" for Firefox (Extensions)
UPDATE categories SET slug="photos-music-videos" WHERE id=38;

-- "RSS, News and Blogging" for SeaMonkey (Extensions)
UPDATE categories SET slug="rss-news-and-blogging" WHERE id=39;

-- "Web and Developer Tools" for SeaMonkey (Extensions)
UPDATE categories SET slug="web-and-developer-tools" WHERE id=41;

-- "Downloading and File Management" for SeaMonkey (Extensions)
UPDATE categories SET slug="downloading-and-file-management" WHERE id=42;

-- "Privacy and Security" for SeaMonkey (Extensions)
UPDATE categories SET slug="privacy-and-security" WHERE id=46;

-- "Search Tools" for SeaMonkey (Extensions)
UPDATE categories SET slug="search-tools" WHERE id=47;

-- "Interface Customizations" for SeaMonkey (Extensions)
UPDATE categories SET slug="interface-customizations" WHERE id=48;

-- "Miscellaneous" for SeaMonkey (Extensions)
UPDATE categories SET slug="miscellaneous" WHERE id=49;

-- "Miscellaneous" for Thunderbird (Extensions)
UPDATE categories SET slug="miscellaneous" WHERE id=50;

-- "Bookmarks" for SeaMonkey (Extensions)
UPDATE categories SET slug="bookmarks" WHERE id=51;

-- "Site-specific" for SeaMonkey (Extensions)
UPDATE categories SET slug="site-specific" WHERE id=52;

-- "Language Support and Translation" for SeaMonkey (Extensions)
UPDATE categories SET slug="language-support-and-translation" WHERE id=55;

-- "Photos and Media" for SeaMonkey (Extensions)
UPDATE categories SET slug="photos-and-media" WHERE id=56;

-- "News Reading" for Thunderbird (Extensions)
UPDATE categories SET slug="news-reading" WHERE id=57;

-- "Message Reading" for Thunderbird (Extensions)
UPDATE categories SET slug="message-reading" WHERE id=58;

-- "Miscellaneous" for SeaMonkey (Themes)
UPDATE categories SET slug="miscellaneous" WHERE id=59;

-- "Miscellaneous" for Thunderbird (Themes)
UPDATE categories SET slug="miscellaneous" WHERE id=60;

-- "OS Integration" for Firefox (Themes)
UPDATE categories SET slug="os-integration" WHERE id=61;

-- "Modern" for Firefox (Themes)
UPDATE categories SET slug="modern" WHERE id=62;

-- "Modern" for Thunderbird (Themes)
UPDATE categories SET slug="modern" WHERE id=63;

-- "Compact" for Thunderbird (Themes)
UPDATE categories SET slug="compact" WHERE id=64;

-- "Nature" for Thunderbird (Themes)
UPDATE categories SET slug="nature" WHERE id=65;

-- "Privacy and Security" for Thunderbird (Extensions)
UPDATE categories SET slug="privacy-and-security" WHERE id=66;

-- "Large" for Firefox (Themes)
UPDATE categories SET slug="large" WHERE id=67;

-- "Language Support" for Thunderbird (Extensions)
UPDATE categories SET slug="language-support" WHERE id=69;

-- "Social & Communication" for Firefox (Extensions)
UPDATE categories SET slug="social-communication" WHERE id=71;

-- "Alerts & Updates" for Firefox (Extensions)
UPDATE categories SET slug="alerts-updates" WHERE id=72;

-- "Other" for Firefox (Extensions)
UPDATE categories SET slug="other" WHERE id=73;

-- "Calendar Enhancements" for Sunbird (Extensions)
UPDATE categories SET slug="calendar-enhancements" WHERE id=74;

-- "Providers" for Sunbird (Extensions)
UPDATE categories SET slug="providers" WHERE id=75;

-- "Language Support and Translation" for Sunbird (Extensions)
UPDATE categories SET slug="language-support-and-translation" WHERE id=76;

-- "General" for Sunbird (Themes)
UPDATE categories SET slug="general" WHERE id=77;

-- "Video" for Firefox (Search Tools)
UPDATE categories SET slug="video" WHERE id=78;

-- "Bookmarks" for Firefox (Search Tools)
UPDATE categories SET slug="bookmarks" WHERE id=79;

-- "Business" for Firefox (Search Tools)
UPDATE categories SET slug="business" WHERE id=80;

-- "Dictionaries & Encyclopedias" for Firefox (Search Tools)
UPDATE categories SET slug="dictionaries-encyclopedias" WHERE id=81;

-- "General" for Firefox (Search Tools)
UPDATE categories SET slug="general" WHERE id=82;

-- "Kids" for Firefox (Search Tools)
UPDATE categories SET slug="kids" WHERE id=83;

-- "Multiple Search" for Firefox (Search Tools)
UPDATE categories SET slug="multiple-search" WHERE id=84;

-- "Music" for Firefox (Search Tools)
UPDATE categories SET slug="music" WHERE id=85;

-- "News & Blogs" for Firefox (Search Tools)
UPDATE categories SET slug="news-blogs" WHERE id=86;

-- "Photos & Images" for Firefox (Search Tools)
UPDATE categories SET slug="photos-images" WHERE id=87;

-- "Shopping & E-Commerce" for Firefox (Search Tools)
UPDATE categories SET slug="shopping-e-commerce" WHERE id=88;

-- "Social & People" for Firefox (Search Tools)
UPDATE categories SET slug="social-people" WHERE id=89;

-- "Sports" for Firefox (Search Tools)
UPDATE categories SET slug="sports" WHERE id=90;

-- "Travel" for Firefox (Search Tools)
UPDATE categories SET slug="travel" WHERE id=91;

-- "Toolbars" for Firefox (Extensions)
UPDATE categories SET slug="toolbars" WHERE id=92;

-- "Tabs" for Firefox (Extensions)
UPDATE categories SET slug="tabs" WHERE id=93;

-- "Experimental" for Mobile (Extensions)
UPDATE categories SET slug="experimental" WHERE id=94;

-- "General" for Firefox (Dictionaries & Language Packs)
UPDATE categories SET slug="general" WHERE id=95;

-- "General" for SeaMonkey (Dictionaries & Language Packs)
UPDATE categories SET slug="general" WHERE id=96;

-- "General" for Thunderbird (Dictionaries & Language Packs)
UPDATE categories SET slug="general" WHERE id=97;

-- "General" for Firefox (5)
UPDATE categories SET slug="general" WHERE id=98;

-- "General" for Thunderbird (5)
UPDATE categories SET slug="general" WHERE id=99;

-- "Abstract" for Firefox (Personas)
UPDATE categories SET slug="abstract" WHERE id=100;

-- "Abstract" for Thunderbird (Personas)
UPDATE categories SET slug="abstract" WHERE id=101;

-- "Nature" for Firefox (Personas)
UPDATE categories SET slug="nature" WHERE id=102;

-- "Nature" for Thunderbird (Personas)
UPDATE categories SET slug="nature" WHERE id=103;

-- "Sports" for Firefox (Personas)
UPDATE categories SET slug="sports" WHERE id=104;

-- "Sports" for Thunderbird (Personas)
UPDATE categories SET slug="sports" WHERE id=105;

-- "Scenery" for Firefox (Personas)
UPDATE categories SET slug="scenery" WHERE id=106;

-- "Scenery" for Thunderbird (Personas)
UPDATE categories SET slug="scenery" WHERE id=107;

-- "Firefox" for Firefox (Personas)
UPDATE categories SET slug="firefox" WHERE id=108;

-- "Firefox" for Thunderbird (Personas)
UPDATE categories SET slug="firefox" WHERE id=109;

-- "Foxkeh" for Firefox (Personas)
UPDATE categories SET slug="foxkeh" WHERE id=110;

-- "Foxkeh" for Thunderbird (Personas)
UPDATE categories SET slug="foxkeh" WHERE id=111;

-- "Seasonal" for Firefox (Personas)
UPDATE categories SET slug="seasonal" WHERE id=112;

-- "Seasonal" for Thunderbird (Personas)
UPDATE categories SET slug="seasonal" WHERE id=113;

-- "Other" for Firefox (Personas)
UPDATE categories SET slug="other" WHERE id=114;

-- "Other" for Thunderbird (Personas)
UPDATE categories SET slug="other" WHERE id=115;

-- "Websites" for Firefox (Personas)
UPDATE categories SET slug="websites" WHERE id=116;

-- "Websites" for Thunderbird (Personas)
UPDATE categories SET slug="websites" WHERE id=117;

-- "Solid" for Firefox (Personas)
UPDATE categories SET slug="solid" WHERE id=118;

-- "Solid" for Thunderbird (Personas)
UPDATE categories SET slug="solid" WHERE id=119;

-- "Causes" for Firefox (Personas)
UPDATE categories SET slug="causes" WHERE id=120;

-- "Causes" for Thunderbird (Personas)
UPDATE categories SET slug="causes" WHERE id=121;

-- "Music" for Firefox (Personas)
UPDATE categories SET slug="music" WHERE id=122;

-- "Music" for Thunderbird (Personas)
UPDATE categories SET slug="music" WHERE id=123;

-- "Fashion" for Firefox (Personas)
UPDATE categories SET slug="fashion" WHERE id=124;

-- "Fashion" for Thunderbird (Personas)
UPDATE categories SET slug="fashion" WHERE id=125;

-- "Film and TV" for Firefox (Personas)
UPDATE categories SET slug="film-and-tv" WHERE id=126;

-- "Film and TV" for Thunderbird (Personas)
UPDATE categories SET slug="film-and-tv" WHERE id=127;

-- "Holiday" for Firefox (Personas)
UPDATE categories SET slug="holiday" WHERE id=128;

-- "Holiday" for Thunderbird (Personas)
UPDATE categories SET slug="holiday" WHERE id=129;

-- "General" for SeaMonkey (5)
UPDATE categories SET slug="general" WHERE id=130;

-- "User Interface" for Mobile (Extensions)
UPDATE categories SET slug="user-interface" WHERE id=131;

-- "Security & Privacy" for Mobile (Extensions)
UPDATE categories SET slug="security-privacy" WHERE id=132;

-- "Shopping" for Mobile (Extensions)
UPDATE categories SET slug="shopping" WHERE id=133;

-- "Social Networking" for Mobile (Extensions)
UPDATE categories SET slug="social-networking" WHERE id=134;

-- "Feeds, News & Blogging" for Mobile (Extensions)
UPDATE categories SET slug="feeds-news-blogging" WHERE id=135;

-- "Sports & Games" for Mobile (Extensions)
UPDATE categories SET slug="sports-games" WHERE id=136;

-- "Device Features & Location" for Mobile (Extensions)
UPDATE categories SET slug="device-features-location" WHERE id=137;

-- "Performance" for Mobile (Extensions)
UPDATE categories SET slug="performance" WHERE id=138;
