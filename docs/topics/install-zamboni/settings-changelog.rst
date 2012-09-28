Settings Changelog
==================


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
