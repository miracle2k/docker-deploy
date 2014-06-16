"""Service-Discovery based on flynn/discoverd and etcd.

While this is in a plugin now, the use of this plugin is still hardcoded
in various places, and more work is needed.
"""

import socket
import time
import yaml

from deploylib.plugins import Plugin


ETCD = """
image: coreos/etcd
# It seems due to the stange way etcdctl connects, we need to set --peer-addr
cmd: -name {HOST} -data-dir /data.etcd -bind-addr=0.0.0.0:{PORT} --peer-addr={HOST}:7001
volumes: {data: /data.etcd}
host_ports: {"": 4001}
"""

DISCOVERD = """
image: flynn/discoverd
cmd: -etcd http://{HOST}:4001
env:
    EXTERNAL_IP: "{HOST}"
ports: {rpc: 1111}
host_ports: {rpc: 1111}
"""

SHELF = """
image: elsdoerfer/shelf
cmd: -s /var/lib/shelf
volumes: {data: /var/lib/shelf}
"""

STROWGER = """
image: elsdoerfer/strowger
cmd: -httpaddr=":{PORT_HTTP}" --httpsaddr=":{PORT_HTTPS}" --apiaddr=":{PORT_RPC}"
ports: [http, https, rpc]
host_ports: {http: "0.0.0.0:80", https: "0.0.0.0:443"}
"""


class DiscoverdEtcdPlugin(Plugin):

    def on_system_init(self):
        self.install('etcd', ETCD, wait=4001)
        self.install('discoverd', DISCOVERD, wait=1111)
        self.install('shelf', SHELF)
        self.install('strowger', STROWGER)

    def install(self, name, definition, wait=None):
        definition = yaml.load(definition)
        self.host.set_service('', name, definition, namer=lambda *a: name)
        if wait:
            is_closed = True
            start_time = time.time()
            print("Waiting for port :%s" % wait)
            while is_closed:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                is_closed = sock.connect_ex((self.host.get_host_ip(), wait))
                sock.close()
                # Wait 30 secs at most
                if time.time() - start_time > 30:
                    print('Cannot connect to port %s for %s' % (wait, name))
                    break

