class NoAuthForYou:
    """An authentication backend for read-only mode."""

    supports_anonymous_user = False
    supports_inactive_user = False
    supports_object_permissions = False

    def authenticate(self, *args, **kw):
        return None

    def get_user(self, *args, **kw):
        return None
