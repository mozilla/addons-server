FROM ubuntu

RUN apt-get update
RUN apt-get install -y memcached

EXPOSE 11211

CMD /usr/bin/memcached -u root
