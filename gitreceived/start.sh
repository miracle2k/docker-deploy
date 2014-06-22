#!/bin/sh

export RECEIVE_DEBUG=/tmp/gitreceive.txt
exec /bin/sdutil exec -s gitreceive:$PORT /bin/gitreceived -k /srv/repos "/bin/bash ssh-key-check" /bin/git-receive-handler
