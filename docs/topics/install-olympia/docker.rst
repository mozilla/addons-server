====================
Install Olympia
====================

.. _install-with-docker:

Want the easiest way to start contributing to AMO? Try our docker-based
development environment.

First you'll need to install docker_, please check the information for
the installation steps specific to your operating system.

.. note::
    Docker recommends installing docker-toolbox_ if you're on OSX or
    windows and that will provide you with the ``docker-machine`` and
    ``docker-compose`` (mac-only).


.. _creating-the-docker-vm:

Creating the docker vm (mac/windows)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you go the docker-machine route your first step is to create a vm::

    docker-machine create --driver=virtualbox addons-dev

Then you can export the variables so that docker-compose can talk to
the docker service. This command will tell you how to do that::

    docker-machine env addons-dev

On a mac it's a case of running::

    eval $(docker-machine env addons-dev)

Setting up the containers
~~~~~~~~~~~~~~~~~~~~~~~~~

Next once you have docker up and running follow these steps
on your host machine::

    git clone git://github.com/mozilla/olympia.git
    cd olympia
    pip install docker-compose
    docker-compose pull  # Can take a while depending on your internet bandwidth.
    docker-compose up -d
    make initialize_docker  # Answer yes, and create your superuser when asked.

Accessing docker
~~~~~~~~~~~~~~~~

The last step is to grab the ip of the vm. If you're using docker-machine,
you can get the ip like so::

    docker-machine ip addons-dev

.. note::
    If you're still using boot2docker then the command is `boot2docker ip`.
    At this point you can look at installing docker-toolbox and migrating
    your old boot2docker vm across to running via docker-machine. See
    docker-toolbox_ for more info.

Now you can connect to port 80 of that ip address. Here's an example
(your ip might be different)::

    http://192.168.99.100/

.. note::
    Bear in mind docker-machine hands out ip addresses as each vm is started;
    so you might find this ip address changes over time. You can always find out
    what ip is being used with ``docker-machine ip [machine name]``

You may need to use a reliable hostname to access your container server (e.g. for
Firefox Accounts). You can set one by editing your ``/etc/hosts`` file on your
native operating system. For example::

    192.168.99.100  olympia.dev

You can ensure your docker server is configured internally with this host by
setting it in the environment and restarting the docker containers, like this::

    export OLYMPIA_SITE_URL=http://olympia.dev
    docker-compose up -d

Running common commands
~~~~~~~~~~~~~~~~~~~~~~~

Any other commands can now be run in a shell on the running container::

    make shell

Then, to run the tests for example, just run this command in the shell::

    py.test

Updating your containers
~~~~~~~~~~~~~~~~~~~~~~~~

Any time you update Olympia (e.g., by running ``git pull``), you should make sure to
update your Docker image and database with any new requirements or migrations::

    docker-compose stop
    docker-compose pull
    docker-compose up -d
    make update_docker  # Runs database migrations and rebuilds assets.

Gotchas!
~~~~~~~~

Please note: any command that would result in files added or modified
outside of the ``olympia`` folder (e.g. modifying pip or npm dependencies) won't be
persisted, and thus won't survive after the running container exits.

.. note::
    If you need to persist any changes to the image, they should be carried out
    via the ``Dockerfile``. Commits to master will result in the Dockerfile being
    rebuilt on the docker hub.

If you quit docker-machine, or restart your computer, docker-machine will need
to be started again using::

    docker-machine start addons-dev

You'll then need to :ref:`export the variables <creating-the-docker-vm>` again,
and start the services::

    docker-compose up -d

Hacking on the Docker image
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you want to test out changes to the Olympia Docker image locally, use the
normal `Docker commands <https://docs.docker.com/reference/commandline/cli/>`_
such as this to build a new image::

    cd olympia
    docker build -t addons/olympia .
    docker-compose up -d

After you've tested your new image, simply commit to master and the
image will be published to Docker Hub for other developers to use after
they pull image changes.

.. _docker: https://docs.docker.com/installation/#installation
.. _docker-toolbox: https://www.docker.com/toolbox
