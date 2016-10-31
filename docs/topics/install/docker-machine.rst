================================
Installation with Docker machine
================================


.. _creating-the-docker-vm:

Creating the docker-machine vm
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Your first step is to create a vm - this step assumes we're using
virtualbox as the driver::

    docker-machine create --driver=virtualbox addons-dev

Then you can export the variables so that docker-compose can talk to
the docker service. This command will tell you how to do that::

    docker-machine env addons-dev

On a mac it's a case of running::

    eval $(docker-machine env addons-dev)

Now you have the vm running you can follow the standard docker
instructions: :ref:`Install with Docker <install-with-docker>`

.. _accessing-the-web-server-docker-machine:

Accessing the web-server with docker-machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you're using docker-machine, you can get the ip like so::

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
    ``docker-machine`` hands out IP addresses as each VM boots; your IP
    addresses can change over time. You can find out which IP is in use using
    ``docker-machine ip [machine name]``

.. _docker-toolbox: https://www.docker.com/toolbox
