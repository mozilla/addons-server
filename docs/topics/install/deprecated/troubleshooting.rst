
=============================================
Trouble-shooting the development installation
=============================================

.. note:: The following documentation is deprecated. The approved installation is :ref:`via Docker <install-with-docker>`.

Image processing isn't working
------------------------------

If adding images to apps or extensions doesn't seem to work then there's a
couple of settings you should check.

Checking your image settings
____________________________

Check that ``CELERY_TASK_ALWAYS_EAGER`` is set to ``True`` in your settings file. This
means it will process tasks without a celery worker running::

    CELERY_TASK_ALWAYS_EAGER = True

If that yields no joy you can try running a celery worker in the foreground,
set ``CELERY_TASK_ALWAYS_EAGER = False`` and run::

    celery -A olympia worker -E


.. note::

    This requires a RabbitMQ server to be set up as detailed in the
    :doc:`./celery` instructions.

This may help you to see where the image processing tasks are failing. For
example it might show that Pillow is failing due to missing dependencies.

Checking your Pillow installation (Ubuntu)
__________________________________________

When you run you should see at least JPEG and ZLIB are supported

If that's the case you should see this in the output of
``pip install -I Pillow``::

    --------------------------------------------------------------------
    *** TKINTER support not available
    --- JPEG support available
    --- ZLIB (PNG/ZIP) support available
    *** FREETYPE2 support not available
    *** LITTLECMS support not available
    --------------------------------------------------------------------

If you don't then this suggests Pillow can't find your image libraries:

To fix this double-check you have the necessary development libraries
installed first (e.g: ``sudo apt-get install libjpeg-dev zlib1g-dev``)

Now run the following for 32bit::

    sudo ln -s /usr/lib/i386-linux-gnu/libz.so /usr/lib
    sudo ln -s /usr/lib/i386-linux-gnu/libjpeg.so /usr/lib

Or this if your running 64bit::

    sudo ln -s /usr/lib/x86_64-linux-gnu/libz.so /usr/lib
    sudo ln -s /usr/lib/x86_64-linux-gnu/libjpeg.so /usr/lib

.. note::

    If you don't know what arch you are running run ``uname -m`` if the
    output is ``x86_64`` then it's 64-bit, otherwise it's 32bit
    e.g. ``i686``


Now re-install Pillow::

    pip install -I Pillow

And you should see the necessary image libraries are now working with
Pillow correctly.


ES is timing out
----------------

This can be caused by ``number_of_replicas`` not being set to 0 for the local indexes.

To check the settings run::

    curl -s localhost:9200/_cluster/state\?pretty | fgrep number_of_replicas -B 5

If you see any that aren't 0  do the following:

Set ``ES_DEFAULT_NUM_REPLICAS`` to ``0`` in your local settings.

To set them to zero immediately run::

    curl -XPUT localhost:9200/_settings -d '{ "index" : { "number_of_replicas" : 0 } }'
