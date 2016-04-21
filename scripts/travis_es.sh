#!/bin/bash

TARGET="/tmp/elasticsearch"

if [ ! -f "$TARGET/elasticsearch-1.6.4/bin/elasticsearch" ]; then
    echo "$TARGET not found. Building..."
    mkdir -p $TARGET
    cd $TARGET
    wget --no-check-certificate https://download.elasticsearch.org/elasticsearch/elasticsearch/elasticsearch-1.6.2.tar.gz
    tar xvf elasticsearch-1.6.2.tar.gz
else
    echo "$TARGET already exists"
fi
