#!/bin/sh

export RECEIVE_DEBUG=/tmp/gitreceive.txt
exec /bin/gitreceived -k /srv/repos "/bin/bash ssh-key-check" /bin/git-receive-handler
