import logging.handlers
import socket


class UnicodeHandler(logging.handlers.SysLogHandler):

    def emit(self, record):
        if hasattr(self, '_fmt') and not isinstance(self._fmt, unicode):
            # Ensure that the formatter does not coerce to str. bug 734422.
            self._fmt = unicode(self._fmt)

        try:
            msg = self.format(record) + '\000'
        except UnicodeDecodeError:
            # At the very least, an error in logging should never propogate
            # up to the site and give errors for our users. This should still
            # be fixed.
            msg =  u'A unicode error occured in logging \000'

        prio = '<%d>' % self.encodePriority(self.facility,
                                            self.mapPriority(record.levelname))
        if type(msg) is unicode:
            msg = msg.encode('utf-8')
        msg = prio + msg
        try:
            if self.unixsocket:
                try:
                    self.socket.send(msg)
                except socket.error:
                    self._connect_unixsocket(self.address)
                    self.socket.send(msg)
            else:
                self.socket.sendto(msg, self.address)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)
