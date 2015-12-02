import logging

getLogger = logging.getLogger


# This can be removed when we go to Python 2.7.
class NullHandler(logging.Handler):

    def emit(self, record):
        pass

# Ensure the creation of the Django logger
# with a null handler. This ensures we don't get any
# 'No handlers could be found for logger "django"' messages
logger = getLogger('django')
if not logger.handlers:
    logger.addHandler(NullHandler())
