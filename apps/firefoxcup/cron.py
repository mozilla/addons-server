import cronjobs
import twitter

@cronjobs.register
def update_twitter():
    """Update Twitter sidebar."""

