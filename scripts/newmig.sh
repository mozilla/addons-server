#!/bin/sh

# Generates the filename for the next available migration.
# usage: ./scripts/newmig.sh <migration-slug>
# % ./scripts/newmig.sh foobar
# > switch generated to 301-foobar.sql

NUM=`ls migrations | sort -n | tail -n1 | awk -F- '{print $1}'`
NUM=$(($NUM+1))
 
echo "$NUM-$1.sql"
