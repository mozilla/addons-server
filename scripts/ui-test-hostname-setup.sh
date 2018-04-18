#!/bin/bash
UI_IP="`docker inspect addonsserver_addons-frontend_1 | grep "IPAddress" | grep -oE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b"`"
echo $UI_IP
HOSTS_LINE="$UI_IP\tlocalhost"
docker-compose exec --user root selenium-firefox sudo -- sh -c -e "echo '$HOSTS_LINE' >> /etc/hosts"
docker-compose exec --user root selenium-firefox cat /etc/hosts
