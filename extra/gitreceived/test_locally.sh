#!/bin/sh

PORT=2233 SSH_PRIVATE_KEYS="$(cat ~/.ssh/id_rsa)" RECEIVE_DEBUG=/tmp/gitreceive.txt ./gitreceived.osx "/bin/sh ssh-key-check.sh" git-receive-handler.sh
