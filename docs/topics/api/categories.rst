==========
Categories
==========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability.

-------------
Category List
-------------

.. _category-list:

Categories are defined by a name, a slug, a type and an application. Slugs are
only guaranteed to be unique for a given ``app`` and ``type`` combination, and
can therefore be re-used for different categories.

This endpoint is not paginated.

.. http:get:: /api/v4/addons/categories/

    :>json int id: The category id.
    :>json string name: The category name. Returns the already translated string.
    :>json string slug: The category slug. See :ref:`csv table <category-csv-table>` for more possible values.
    :>json string application: Application, see :ref:`add-on application <addon-detail-application>` for more details.
    :>json boolean misc: Whether or not the category is miscellaneous.
    :>json string type: Category type, see :ref:`add-on type <addon-detail-type>` for more details.
    :>json int weight: Category weight used in sort ordering.
    :>json string description: The category description. Returns the already translated string.


.. _category-csv-table:

------------------
Current categories
------------------

.. csv-table::
   :header: "Name", "Slug", "Type", "Application"

    "Alerts & Updates", alerts-updates, extension, firefox
    "Appearance", appearance, extension, firefox
    "Bookmarks", bookmarks, extension, firefox
    "Download Management", download-management, extension, firefox
    "Feeds, News & Blogging", feeds-news-blogging, extension, firefox
    "Games & Entertainment", games-entertainment, extension, firefox
    "Language Support", language-support, extension, firefox
    "Photos, Music & Videos", photos-music-videos, extension, firefox
    "Privacy & Security", privacy-security, extension, firefox
    "Search Tools", search-tools, extension, firefox
    "Shopping", shopping, extension, firefox
    "Social & Communication", social-communication, extension, firefox
    "Tabs", tabs, extension, firefox
    "Web Development", web-development, extension, firefox
    "Other", other, extension, firefox
    "Animals", animals, theme, firefox
    "Compact", compact, theme, firefox
    "Large", large, theme, firefox
    "Miscellaneous", miscellaneous, theme, firefox
    "Modern", modern, theme, firefox
    "Nature", nature, theme, firefox
    "OS Integration", os-integration, theme, firefox
    "Retro", retro, theme, firefox
    "Sports", sports, theme, firefox
    "General", general, dictionary, firefox
    "Bookmarks", bookmarks, search, firefox
    "Business", business, search, firefox
    "Dictionaries & Encyclopedias", dictionaries-encyclopedias, search, firefox
    "General", general, search, firefox
    "Kids", kids, search, firefox
    "Multiple Search", multiple-search, search, firefox
    "Music", music, search, firefox
    "News & Blogs", news-blogs, search, firefox
    "Photos & Images", photos-images, search, firefox
    "Shopping & E-Commerce", shopping-e-commerce, search, firefox
    "Social & People", social-people, search, firefox
    "Sports", sports, search, firefox
    "Travel", travel, search, firefox
    "Video", video, search, firefox
    "General", general, language, firefox
    "Abstract", abstract, persona, firefox
    "Causes", causes, persona, firefox
    "Fashion", fashion, persona, firefox
    "Film and TV", film-and-tv, persona, firefox
    "Firefox", firefox, persona, firefox
    "Foxkeh", foxkeh, persona, firefox
    "Holiday", holiday, persona, firefox
    "Music", music, persona, firefox
    "Nature", nature, persona, firefox
    "Other", other, persona, firefox
    "Scenery", scenery, persona, firefox
    "Seasonal", seasonal, persona, firefox
    "Solid", solid, persona, firefox
    "Sports", sports, persona, firefox
    "Websites", websites, persona, firefox
    "Appearance and Customization", appearance, extension, thunderbird
    "Calendar and Date/Time", calendar, extension, thunderbird
    "Chat and IM", chat, extension, thunderbird
    "Contacts", contacts, extension, thunderbird
    "Folders and Filters", folders-and-filters, extension, thunderbird
    "Import/Export", importexport, extension, thunderbird
    "Language Support", language-support, extension, thunderbird
    "Message Composition", composition, extension, thunderbird
    "Message and News Reading", message-and-news-reading, extension, thunderbird
    "Miscellaneous", miscellaneous, extension, thunderbird
    "Privacy and Security", privacy-and-security, extension, thunderbird
    "Tags", tags, extension, thunderbird
    "Compact", compact, theme, thunderbird
    "Miscellaneous", miscellaneous, theme, thunderbird
    "Modern", modern, theme, thunderbird
    "Nature", nature, theme, thunderbird
    "General", general, dictionary, thunderbird
    "General", general, language, thunderbird
    "Bookmarks", bookmarks, extension, seamonkey
    "Downloading and File Management", downloading-and-file-management, extension, seamonkey
    "Interface Customizations", interface-customizations, extension, seamonkey
    "Language Support and Translation", language-support-and-translation, extension, seamonkey
    "Miscellaneous", miscellaneous, extension, seamonkey
    "Photos and Media", photos-and-media, extension, seamonkey
    "Privacy and Security", privacy-and-security, extension, seamonkey
    "RSS, News and Blogging", rss-news-and-blogging, extension, seamonkey
    "Search Tools", search-tools, extension, seamonkey
    "Site-specific", site-specific, extension, seamonkey
    "Web and Developer Tools", web-and-developer-tools, extension, seamonkey
    "Miscellaneous", miscellaneous, theme, seamonkey
    "General", general, dictionary, seamonkey
    "General", general, language, seamonkey
    "Device Features & Location", device-features-location, extension, android
    "Experimental", experimental, extension, android
    "Feeds, News, & Blogging", feeds-news-blogging, extension, android
    "Performance", performance, extension, android
    "Photos & Media", photos-media, extension, android
    "Security & Privacy", security-privacy, extension, android
    "Shopping", shopping, extension, android
    "Social Networking", social-networking, extension, android
    "Sports & Games", sports-games, extension, android
    "User Interface", user-interface, extension, android
