================================
Using the VPN with docker on OSX
================================

If you need to access services behind a VPN, the docker setup should by
default allow outgoing traffic over the VPN as it does for your host.
If this isn't working you might find that it will work if you start up
the vm *after* you have started the VPN connection.

To do this simply stop the containers::

    docker-compose stop

Stop the docker-machine vm::

    # Assumes you've called the vm 'addons-dev'
    docker-machine stop addons-dev

Then connect to your VPN and restart the docker vm::

    docker-machine start addons-dev

and fire up the env containers again::

    docker-compose up -d
