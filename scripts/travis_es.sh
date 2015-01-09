#!/bin/bash

TARGET="/tmp/elasticsearch"

if [ ! -f "$TARGET/elasticsearch-1.2.4/bin/elasticsearch" ]; then
    echo "$TARGET not found. Building..."
    pushd $TARGET
    wget https://download.elasticsearch.org/elasticsearch/elasticsearch/elasticsearch-1.3.2.tar.gz
    tar xvf elasticsearch-1.3.2.tar.gz
else
    echo "$TARGET already exists"
fi
