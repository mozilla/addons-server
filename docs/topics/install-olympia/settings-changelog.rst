Settings Changelog
==================

2014-07-09
----------
All the media related `XXX_PATH` and `XXX_URL` settings have now been
deprecated, in favor of helpers `storage_url` and `storage_path`, during
the switch to `django.contrib.staticfiles`. `JINGO_MINIFY_USE_STATIC` is
also now set to True.



2014-04-25
----------

* Added ``'django.contrib.staticfiles'`` to the ``INSTALLED_APPS``, as it's
  needed by the latest versions of DDT.
* Added ``DEBUG_TOOLBAR_PATCH_SETTINGS = False`` to prevent DDT from patching
  the settings on its own (it would create an import loop).
* Removed ``DEBUG_TOOLBAR_CONFIG`` as it's not used anymore with the latest
  versions of DDT.


2014-01-22
----------

* Changed ``CACHES['default']['BACKEND']`` from
  ``django.core.cache.backends.locmem.LocMemCache`` to 
  ``caching.backends.locmem.LocMemCache``.
  We use the LocMemCache backend from cache-machine, as it interprets the
  "0" timeout parameter of ``cache`` in the same way as the Memcached backend:
  as infinity. Django's LocMemCache backend interprets it as a "0 seconds"
  timeout (and thus doesn't cache at all).

2013-08-09
----------
* Added ``AES_KEYS`` as a settings for encrypting OAuth secrets. Uses a sample
  by default, set this on a production server to something else.

2013-06-28
----------
* Added ``ES_USE_PLUGINS``. Some features of Elasticsearch require
  installed plugins. To bypass requiring these plugins locally set this to
  `False`. On our servers this should be `True`.

2013-05-24
----------
* Added ``ES_DEFAULT_NUM_REPLICAS``. Locally if you're running a single
  Elasticsearch node you probably want to set this to 0 (zero).
* Added ``ES_DEFAULT_NUM_SHARDS``. Locally 3 shards is sufficient.

2012-04-12
----------
* Removed ``GEOIP_NOOP``, ``GEOIP_HOST``, and ``GEOIP_PORT`` as they are no
  longer used.
* Added ``GEOIP_URL`` which is the fully qualified URL to your locally running
  `geodude <https://github.com/mozilla/geodude>` instance without trailing
  slash.
* Changed default ``GEOIP_DEFAULT_VAL`` to ``'worldwide'``.


2012-04-01
----------
* Added ``PACKAGED_ZIP`` setting, which is the base filename of the ``.zip``
  containing the packaged app for the consumer-facing pages of the Marketplace.
* Removed ``FIREPLACE_SECRET_KEY`` setting since ``SECRET_KEY`` is already
  used for making user secrets and we need something immediately.

2012-03-28
----------
* Added ``FIREPLACE_SECRET_KEY`` setting, used for creating shared
  secrets for API login from the marketplace frontend.

2012-03-13
----------
* Added ``FIREPLACE_URL`` setting, for the origin URL of the
  Marketplace frontend.

2012-02-25
----------
* Removed ``MDN_LAZY_REFRESH`` setting.

2012-11-14
----------
* Added ``MDN_LAZY_REFRESH`` which allows you to append `?refresh` to
  https://marketplace-dev.allizom.org/developers/ and
  https://marketplace-dev.allizom.org/developers/docs/ to refresh all content
  from MDN for the Developer Hub. In production this should always remain
  ``False``.

2012-09-27
----------
* Added ``ALLOW_SELF_REVIEWS`` which allows you to approve/reject your own
  add-ons and apps. This is especially useful for testing on our staging
  and -dev servers. In production this should always remain ``False``.

2012-09-25
----------
* Added ``settings changelog``
  * This will give us an area to mention new settings (and mark them as
    optional) so people can look to see what has happened in settings-land.
* Removed ``confusion`` (optional)
  * Using 'Added' and 'Removed' and 'Changed' as the start of your lines gives a
    nice way to quickly read these.
* Changed default ``way to find changes`` from ``ask in IRC`` to ``check the
  changelog``
  * We can debate the format, but this gives us a starting point.
