FROM ubuntu:12.04

RUN apt-get update && apt-get -qy install git && apt-get clean
RUN apt-get install -qy python-setuptools
RUN easy_install httpie

ADD start.sh /bin/start
ADD utils.sh /bin/utils.sh
ADD git-receive-handler.sh /bin/git-receive-handler
ADD ssh-key-check.sh /bin/ssh-key-check
ADD gitreceived /bin/gitreceived
ADD sdutil /bin/sdutil

VOLUME /srv/repos
ENTRYPOINT ["/bin/start"]
