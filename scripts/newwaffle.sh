#!/bin/sh

# Generates a waffle switch migration for a given switch slug.
# usage: ./scripts/newwaffle.sh <waffle-switch-name>
# % ./scripts/newwaffle.sh foobar
# > switch generated to 301-waffle-foobar.sql

NEWFILE=`./scripts/newmig.sh waffle-$1`

echo "INSERT INTO waffle_switch (name, active) VALUES ('$1', 0);
" > ./migrations/$NEWFILE

echo "switch generated to $NEWFILE"