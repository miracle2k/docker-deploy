# Wrap the command in sdutil calls if desired. This requires the
# images to a) have /sdutil b) not rely on an entrypoint.
if 'register' in service:
    cmd = service.cmd
    for port, pname in service.register.items():
        cmd = '/sdutil exec -i eth0 {did}:{sname}:{pname}:{p} {cmd}'.format(
            did=deploy_id, sname=service.name, pname=pname, p=port, cmd=cmd)
    service.cmd = cmd[len('/sdutil '):]
    service.entrypoint = '/sdutil'

expose code here as well


class InjectSdutil(Plugin):
    def before_start(self, container, service):
        if service.inject:
            pass