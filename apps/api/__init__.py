MIN_VERSION = 1.0
CURRENT_VERSION = 1.5
MAX_VERSION = CURRENT_VERSION

from django.db.models.signals import post_save, post_delete
from piston.models import consumer_post_save, consumer_post_delete, Consumer

# Do not want.
post_save.disconnect(consumer_post_save, sender=Consumer)
post_delete.disconnect(consumer_post_delete, sender=Consumer)
