def log_create(action, *args, **kw):
    """Use this if importing ActivityLog causes a circular import."""
    from olympia.activity.models import ActivityLog

    return ActivityLog.objects.create(action, *args, **kw)
