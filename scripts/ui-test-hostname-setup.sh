#!/bin/bash
# This script sets the ip of the addons-frontend image as localhost within the selenium-firefox image.
# This MUST be run before any user integration tests.

UI_IP="`docker inspect addons-server_addons-frontend_1 | grep "IPAddress" | grep -oE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b"`"
echo $UI_IP
HOSTS_LINE="$UI_IP\tlocalhost"
docker-compose exec --user root selenium-firefox sudo -- sh -c -e "echo '$HOSTS_LINE' >> /etc/hosts"
docker-compose exec --user root selenium-firefox cat /etc/hosts
