====================
Install with Docker
====================

.. _install-with-docker:

Want the easiest way to start contributing to AMO? Try our Docker-based
development environment.

First you'll need to install Docker_. Please read their docs for
the installation steps specific to your operating system.

There are two options for running docker depending on the platform
you are running.

 * Run docker on the host machine directly (recommended)
 * Run docker-machine which will run docker inside a virtual-machine

Historically Mac and Windows could only run Docker via a vm. That has
recently changed with the arrival of docker-for-mac_ and docker-for-windows_.

If your platform can run Docker directly either on Linux, with docker-for-mac_
or docker-for-windows_ then this is the easiest way to run ``addons-server``.

If you have problems, due to not meeting the minimum specifications for
docker-for-windows_ or you'd prefer to keep running docker-machine vms then
docker-machine will still work just fine. See the docs for creating the
vm here :ref:`creating-the-docker-vm`

.. note::
    If you're on a Mac and already have a working docker-machine setup you
    can run that and docker-for-mac (*but not docker-for-windows*) side by side.
    The only caveat is it's recommended that you keep the versions of Docker on
    the vm and the host in-sync to ensure compatibility when you switch between
    them.

Setting up the containers
~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::
    docker-toolbox, docker-for-mac and docker-for-windows will install ``docker-compose``
    for you. If you're on Linux and you need it, you can install it manually with::

        pip install docker-compose

Next once you have Docker up and running follow these steps
on your host machine::

    # Checkout the addons-server sourcecode.
    git clone git://github.com/mozilla/addons-server.git
    cd addons-server
    # Download the containers
    docker-compose pull  # Can take a while depending on your internet bandwidth.
    # Start up the containers
    docker-compose up -d
    make initialize_docker  # Answer yes, and create your superuser when asked.
    # On Windows you can substitute `make initialize_docker` for the command:
    docker-compose exec web make initialize

.. note::

   Docker requires the code checkout to exist within your home directory so
   that Docker can mount the source-code into the container.

Accessing the web server
~~~~~~~~~~~~~~~~~~~~~~~~

By default our docker-compose config exposes the web-server on port 80 of localhost.

We use ``olympia.dev`` as the default hostname to access your container server (e.g. for
Firefox Accounts). To be able access the development environment using ``http://olympia.dev``
you'll need to  edit your ``/etc/hosts`` file on your native operating system.
For example::

    [ip-address]  olympia.dev

Typically the IP address is localhost (127.0.0.1) but if you're using docker-machine
see :ref:`accessing-the-web-server-docker-machine` for details of how to get the ip of
the Docker vm.

By default we configure `OLYMPIA_SITE_URL` to point to `http://olympia.dev`.

If you choose a different hostname you'll need to set that environment variable
and restart the Docker containers::

    docker-compose stop # only needed if running
    export OLYMPIA_SITE_URL=http://[YOUR_HOSTNAME}
    docker-compose up -d


Running common commands
~~~~~~~~~~~~~~~~~~~~~~~

Run the tests using ``make``, *outside* of the Docker container::

    make test
    # or
    docker-compose exec web py.test src/olympia/

You can run commands inside the Docker container by ``ssh``\ing into it using::

    make shell
    # or
    docker-compose exec web bash

Then to run the tests inside the Docker container you can run::

    py.test

You can also run single commands from your host machine without opening a shell
on each container. Here is an example of running the ``py.test`` command on the
``web`` container::

    docker-compose run web py.test

If you'd like to use a python debugger to interactively
debug Django view code, check out the :ref:`debugging` section.

.. note::
    If you see an error like ``No such container: addonsserver_web_1`` and
    your containers are running you can overwrite the base name for docker
    containers with the ``COMPOSE_PROJECT_NAME`` environment variable. If your
    container is named ``localaddons_web_1`` you would set
    ``COMPOSE_PROJECT_NAME=localaddons``.

Updating your containers
~~~~~~~~~~~~~~~~~~~~~~~~

Any time you update Olympia (e.g., by running ``git pull``), you should make
sure to update your Docker image and database with any new requirements or
migrations::

    docker-compose stop
    docker-compose pull
    docker-compose up -d
    make update_docker  # Runs database migrations and rebuilds assets.
    # On Windows you can substitute `make update_docker` for the following two commands:
    docker-compose exec worker make update_deps
    docker-compose exec web make update

Gotchas!
~~~~~~~~

Here's a list of a few of the issues you might face when using Docker.

Can't access the web server?
----------------------------

Check you've created a hosts file entry pointing ``olympia.dev`` to the
relevant IP address.

If containers are failing to start use ``docker-compose ps`` to check their
running status.

Another way to find out what's wrong is to run ``docker-compose logs``.

Getting "Programming error [table] doesn't exist"?
--------------------------------------------------

Make sure you've run the ``make initialize_docker`` step as detailed in
the initial setup instructions.


ConnectionError during initialize_docker (elasticsearch container fails to start)
---------------------------------------------------------------------------------
When running ``make initialize_docker`` without a working elasticsearch container,
you'll get a ConnectionError. Check the logs with ``docker-compose logs``.
If elasticsearch is complaining about ``vm.max_map_count``, run this command on your computer
or your docker-machine VM:

``sudo sysctl -w vm.max_map_count=262144``

This allows processes to allocate more `memory map areas`_.


Port collisions (nginx container fails to start)
------------------------------------------------


If you're already running a service on port 80 or 8000 on your host machine,
the ``nginx`` container will fail to start. This is because the
``docker-compose.override.yml`` file tells ``nginx`` to listen on port 80
and the web service to listen on port 8000 by default.

This problem will manifest itself by the services failing to start. Here's an
example for the most common case of ``nginx`` not starting due to a collision on
port 80::

    ERROR: for nginx  Cannot start service nginx:.....
    ...Error starting userland proxy: Bind for 0.0.0.0:80: unexpected error (Failure EADDRINUSE)
    ERROR: Encountered errors while bringing up the project.

You can check what's running on that port by using (sudo is required if
you're looking at port < 1024)::

    sudo lsof -i :80

We specify the ports ``nginx`` listens on in the ``docker-compose.override.yml``
file. If you wish to override the ports you can do so by creating a new ``docker-compose``
config and starting the containers using that config alongside the default config.

For example if you create a file called ``docker-compose-ports.yml``::

    nginx:
      ports:
        - 8880:80

Next you would stop and start the containers with the following::

    docker-compose stop # only needed if running
    docker-compose -f docker-compose.yml -f docker-compose-ports.yml up -d

Now the container ``nginx`` is listening on 8880 on the host. You can now proxy
to the container ``nginx`` from the host ``nginx`` with the following ``nginx`` config::

    server {
        listen       80;
        server_name  olympia.dev;
        location / {
            proxy_pass   http://olympia.dev:8880;
        }
    }

Persisting changes
------------------

Please note: any command that would result in files added or modified
outside of the ``addons-server`` folder (e.g. modifying pip or npm
dependencies) won't persist, and thus won't survive after the
running container exits.

.. note::
    If you need to persist any changes to the image, they should be carried out
    via the ``Dockerfile``. Commits to master will result in the Dockerfile
    being rebuilt on the Docker hub.

Restarting docker-machine vms following a reboot
------------------------------------------------

If you quit docker-machine, or restart your computer, docker-machine will need
to start again using::

    docker-machine start addons-dev

You'll then need to :ref:`export the variables <creating-the-docker-vm>` again,
and start the services::

    docker-compose up -d

Hacking on the Docker image
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you want to test out changes to the Olympia Docker image locally, use the
normal `Docker commands <https://docs.docker.com/engine/reference/commandline/docker/>`_
such as this to build a new image::

    cd addons-server
    docker build -t addons/addons-server .
    docker-compose up -d

After you test your new image, commit to master and the image will be published
to Docker Hub for other developers to use after they pull image changes.

.. _Docker: https://docs.docker.com/installation/#installation
.. _docker-toolbox: https://www.docker.com/toolbox
.. _docker-for-windows: https://docs.docker.com/engine/installation/windows/#/docker-for-windows
.. _docker-for-mac: https://docs.docker.com/engine/installation/mac/#/docker-for-mac
.. _memory map areas: https://stackoverflow.com/a/11685165/4496684
