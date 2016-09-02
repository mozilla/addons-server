====================
Install with Docker
====================

.. _install-with-docker:

Want the easiest way to start contributing to AMO? Try our docker-based
development environment.

First you'll need to install docker_, please check the information for
the installation steps specific to your operating system.

There are generally two options for running docker depending on the platform
you are running.

 * Run docker on the host machine directly (recommended if supported)
 * Run docker-machine which will run docker inside a virtual-machine

Historically mac and windows could only run docker via a vm. That has
recently changed with the arrival of docker-for-mac_ and docker-for-windows_.

If your platform can run docker directly either on Linux, with docker-for-mac_
or docker-for-windows_ then this is the easiest way to install docker with the
most minimal set of moving parts.

If you have problems, due to not meeting the requirenents or you're on windows
and want to keep running docker-machine vms then docker-machine will still
work just fine. See the docs for creating the vm here :ref:`creating-the-docker-vm`

.. note:: if you're on OSX and already have a working docker-machine setup you
   can run that and docker-for-mac (*but not docker-for-windows*) side by side.
   The only caveat here  is that it's recommended that you keep the versions of
   docker on the vm and the host in-sync to ensure compatibility when you switch
   between them.

Setting up the containers
~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

    docker-toolbox, docker-for-mac and docker-for-windows will install ``docker-compose``
    for you. If you're on linux and you need it, you can install it manually with::

        pip install docker-compose

Next once you have docker up and running follow these steps
on your host machine::

    # Checkout the addons-server sourcecode.
    git clone git://github.com/mozilla/addons-server.git
    cd addons-server
    # Create the docker-compose.override file with the default ports.
    cp docker-compose.override.yml{.tmpl,}
    # Download the containers
    docker-compose pull  # Can take a while depending on your internet bandwidth.
    # Start up the containers
    docker-compose up -d
    make initialize_docker  # Answer yes, and create your superuser when asked.

.. note::

   Generally docker requires the code checkout to exist within your home directory so
   that docker can mount the source-code into the container.

Accessing the web server
~~~~~~~~~~~~~~~~~~~~~~~~

By default our docker-compose config exposes the web-server on port 80 of localhost.

We use olympia.dev as the default hostname to access your container server (e.g. for
Firefox Accounts). To be able access the development environment using http://olympia.dev
you'll need to  edit your ``/etc/hosts`` file on your native operating system.
For example::

    [ip-address]  olympia.dev

Typically the ip address is localhost 127.0.0.1 if you're using docker-machine
see :ref:`accessing-the-web-server-docker-machine` for details of how to get the ip of
the docker vm.

You can ensure your docker server is configured internally with this host by
setting it in the environment and restarting the docker containers, like this::

    docker-compose stop # only needed if running
    export OLYMPIA_SITE_URL=http://olympia.dev
    docker-compose up -d

.. note::
    The default docker configuration already configures `OLYMPIA_SITE_URL` to
    be set to `http://olympia.dev`

Running common commands
~~~~~~~~~~~~~~~~~~~~~~~

Run the tests using ``make``, *outside* of the docker container::

    make test

You can run commands inside the docker container by ``ssh``\ing into it using::

    make shell

Then to run the tests inside the docker container you can run::

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

Gotchas!
~~~~~~~~

Here's a list of a few of the issues you might face when using docker.

Can't access the web server?
----------------------------

Check you've created an hosts file entry pointing ``olympia.dev`` to the
relevant ip address.

Also make sure you've copied ``docker-compose.override.yml.tmpl`` to
``docker-compose.override.yml`` to get the default ports. If you haven't
stop the containers with ``docker-compose stop`` copy the file and restart
with ``docker-compose up -d``.

Another tip is to use ``docker-compose ps`` to check the status of the
containers. If they are failing to start you should be able to tell here.

Another way to find out what's wrong is to run ``docker-compose logs``.

Getting "Programming error [table] doesn't exist"?
--------------------------------------------------

Check you've run the ``make initialize_docker`` step.


Port collisions (nginx container fails to start)
------------------------------------------------

Since by default the docker-compose file exposes the port to the nginx
server that sits in front of the web service on port 80 on your host
you might find it fails to start if you're already running a service on
port 80.

This problem will manifest itself by the services failing to start, you'll
be able to see the error like so::

    ERROR: for nginx  Cannot start service nginx:.....
    ...Error starting userland proxy: Bind for 0.0.0.0:80: unexpected error (Failure EADDRINUSE)
    ERROR: Encountered errors while bringing up the project.

There's a couple of ways to fix it. Simple one is to find out what's running on
port 80 and stop it::

    sudo lsof -i :80

We now specify the ports nginx listens on in the ``docker-compose.override.yml``
file that you copied from ``docker-compose.override.yml.tmpl`` when going through
the initial setup. The second solution to a port collision is to change the
default port that's bound on the host.

If you need to change the ports you can do so by changing the defaults in
``docker-compose.override.yml``.

For example if you want to run nginx on your host and still
access the development environment on port 80 you can change
``docker-compose.override.yml`` to this::

    nginx:
      ports:
        - 8880:80

Now the container nginx is listening on 8880 on the host. You can now proxy
to the container nginx from the host nginx with the following nginx config::

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
    being rebuilt on the docker hub.

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
normal `Docker commands <https://docs.docker.com/reference/commandline/cli/>`_
such as this to build a new image::

    cd addons-server
    docker build -t addons/addons-server .
    docker-compose up -d

After you test your new image, commit to master and the image will be published
to Docker Hub for other developers to use after they pull image changes.

.. _docker: https://docs.docker.com/installation/#installation
.. _docker-toolbox: https://www.docker.com/toolbox
.. _docker-for-windows: https://docs.docker.com/engine/installation/windows/#/docker-for-windows
.. _docker-for-mac: https://docs.docker.com/engine/installation/mac/#/docker-for-mac
