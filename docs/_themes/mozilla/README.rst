Mozilla sphinx's theme
######################

This is a version of Mozilla's sandstone theme, for `the Sphinx documentation
engine. <http://sphinx.pocoo.org>`_.

Here is how I use it
====================

To use it, you need to clone it somewhere in your Sphinx's architecture::

    $ cd docs/source && mkdir _themes
    $ git clone https://github.com/ametaireau/mozilla-sphinx-theme.git _themes/mozilla

and to configure Sphinx to use it. In your `conf.py` file::

    html_theme_path = ['_themes']
    html_theme = 'mozilla'

Take care and remove the `pygments_style` configuration, as it may not be of
the better taste with the mozilla's theme.

Any contributions are of course welcome!
