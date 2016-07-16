import logging

getLogger = logging.getLogger


# Ensure the creation of the Django logger
# with a null handler. This ensures we don't get any
# 'No handlers could be found for logger "django"' messages
logger = getLogger('django')
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
