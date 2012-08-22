import subprocess


def check_output(*popenargs, **kwargs):
    # Tell thee, check_output was from Python 2.7 untimely ripp'd.
    # check_output shall never vanquish'd be until
    # Marketplace moves to Python 2.7.
    if 'stdout' in kwargs:
        raise ValueError('stdout argument not allowed, it will be overridden.')
    process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
    output, unused_err = process.communicate()
    retcode = process.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]
        error = subprocess.CalledProcessError(retcode, cmd)
        error.output = output
        raise error
    return output


class VideoBase(object):

    def __init__(self, filename):
        self.filename = filename
        self.meta = None
        self.errors = []

    def _call(self):
        raise NotImplementedError

    def get_encoded(self, size):
        raise NotImplementedError

    def get_screenshot(self, size):
        raise NotImplementedError

    def get_meta(self):
        pass

    @classmethod
    def library_available(cls):
        pass

    def is_valid(self):
        return
