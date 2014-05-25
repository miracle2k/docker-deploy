# For development purposes, this should mount the local directory,
# but for now, on OSX with boot2docker, this is a challenge.

FROM ubuntu

RUN apt-get update && apt-get -y upgrade

RUN apt-get install -y python python-setuptools
RUN apt-get install -y gcc python-dev

ADD . /opt
RUN cd /opt && python setup.py develop

ADD docker/runner.sh /runner
RUN chmod +x /runner

# This will be a path on the host
ENV DEPLOY_DATA /srv/deployd
# This will be a path in the container
ENV DEPLOY_STATE /data/db

ENTRYPOINT ["/runner"]
# AAAAARG https://github.com/dotcloud/docker/issues/3762
CMD ["deployd"]
