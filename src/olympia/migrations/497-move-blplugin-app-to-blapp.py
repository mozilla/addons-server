from apps.blocklist.models import BlocklistApp, BlocklistPlugin


def run():
    # only blocked plugins with all 3 are app based blocks, otherwise the
    # min/max refer to the version of the plugin.
    plugins = (
        BlocklistPlugin.objects.exclude(min='')
        .exclude(min=None)
        .exclude(max='')
        .exclude(max=None)
        .exclude(guid='')
        .exclude(guid=None)
    )

    for plugin in plugins:
        if plugin.guid and plugin.min and plugin.max:
            BlocklistApp.objects.create(
                blplugin=plugin,
                guid=plugin.guid,
                min=plugin.min,
                max=plugin.max,
            )
            # Null out the fields so the migration can be resumed if
            # interrupted. This way when the guid field is removed, the min and
            # max wont be treated like plugin min and max when they are app min
            # and max.
            plugin.guid = None
            plugin.min = None
            plugin.max = None
            plugin.save()
