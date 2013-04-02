Settings Changelog
==================

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
