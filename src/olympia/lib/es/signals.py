from django.dispatch import Signal

# This resets the messages that were going to go to ES.
reset = Signal(providing_args=[])
# This sends all the messages to ES and then resets the queue.
process = Signal(providing_args=[])
