import logging.handlers
import socket


class UnicodeHandler(logging.handlers.SysLogHandler):

    def emit(self, record):
        msg = self.format(record) + '\000'
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
