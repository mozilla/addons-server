"""Built-in license texts"""

import os.path


def license_text(shortname):
    licensefile = os.path.join(os.path.dirname(__file__),
                               '%s.txt' % shortname)
    with open(licensefile, 'r') as text:
        return text.read()
