from olympia.stats.models import ThemeUpdateCount, UpdateCount


def migrate_theme_update_count(lwt, static_theme, **kw):
    """Create UpdateCount instances from ThemeUpdateCount instances.
    By default all instances for the specified lwt (lightweight theme) are
    copied.  Any additional **kw are passed to the filter to - for example to
    limit to a certain day or day range."""
    theme_update_counts = ThemeUpdateCount.objects.filter(
        addon_id=lwt.id, **kw
    ).iterator()
    update_counts = [
        UpdateCount(addon_id=static_theme.id, date=tuc.date, count=tuc.count)
        for tuc in theme_update_counts
    ]
    UpdateCount.objects.bulk_create(update_counts, 100)
