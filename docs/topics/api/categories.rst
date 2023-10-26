==========
Categories
==========

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.

-------------
Category List
-------------

.. _category-list:

Categories are defined by a name, a slug and a type. Slugs are
only guaranteed to be unique for a given ``type``, and can therefore be re-used
for different categories.

This endpoint is not paginated.

.. http:get:: /api/v5/addons/categories/

    :>json int id: The category id.
    :>json string name: The category name. Returns the already translated string.
    :>json string slug: The category slug. See :ref:`csv table <category-csv-table>` for more possible values.
    :>json boolean misc: Whether or not the category is miscellaneous.
    :>json string type: Category type, see :ref:`add-on type <addon-detail-type>` for more details.
    :>json int weight: Category weight used in sort ordering.
    :>json string|null description: The category description. Returns the already translated string.


.. _category-csv-table:

------------------
Current categories
------------------

.. csv-table::
   :header: "Name", "Slug", "Type"

    "Alerts & Updates", alerts-updates, extension
    "Appearance", appearance, extension
    "Bookmarks", bookmarks, extension
    "Download Management", download-management, extension
    "Feeds, News & Blogging", feeds-news-blogging, extension
    "Games & Entertainment", games-entertainment, extension
    "Language Support", language-support, extension
    "Photos, Music & Videos", photos-music-videos, extension
    "Privacy & Security", privacy-security, extension
    "Search Tools", search-tools, extension
    "Shopping", shopping, extension
    "Social & Communication", social-communication, extension
    "Tabs", tabs, extension
    "Web Development", web-development, extension
    "Other", other, extension
    "General", general, dictionary
    "General", general, language
    "Abstract", abstract, statictheme
    "Causes", causes, statictheme
    "Fashion", fashion, statictheme
    "Film and TV", film-and-tv, statictheme
    "Firefox", firefox, statictheme
    "Foxkeh", foxkeh, statictheme
    "Holiday", holiday, statictheme
    "Music", music, statictheme
    "Nature", nature, statictheme
    "Other", other, statictheme
    "Scenery", scenery, statictheme
    "Seasonal", seasonal, statictheme
    "Solid", solid, statictheme
    "Sports", sports, statictheme
    "Websites", websites, statictheme
