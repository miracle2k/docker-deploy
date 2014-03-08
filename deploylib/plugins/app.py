from . import Plugin


class AppPlugin(Plugin):
    """Will run a 12-factor style app.
    """

    def build(self, deploy_id, service):
        e = self.e
        l = lambda cmd, *a, **kw: self.e(local, cmd.format(*a, **kw), capture=True)

        # Detect the shelve service first
        shelf_ip = self.host.discover('shelf')

        # The given path may be a subdirectory of a repo
        # For git archive to work right we need the sub path relative
        # to the repository root.
        project_path = service.path(service.git)
        with directory(project_path):
            git_root = l('git rev-parse --show-toplevel')
            gitsubdir = project_path[len(git_root):]

        # Determine git version
        with directory(project_path):
            app_version = l('git rev-parse HEAD')[:10]

        release_id = "{}/{}:{}".format(deploy_id, service.name, app_version)
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))

        # Check if the file exists already
        statuscode = e(run, "curl -s -o /dev/null -w '%{http_code}' --head " + slug_url)
        if statuscode == '200':
            return slug_url

        # Create and push the git archive
        remote_temp = '/tmp/{}'.format(uuid.uuid4().hex)
        with directory(project_path):
            temp = tempfile.mktemp()
            l('git archive HEAD:{} > {}', gitsubdir, temp)
            e(put, temp, remote_temp)
            l('rm {}', temp)

        # Build into a slug
        # Note: buildstep would give us a real exclusive image, rather than a
        # container that presumably needs to unpack the slug every time. Maybe
        # we could also commit the slugrunner container after the first run?
        cache_dir = self.host.cache('slugbuilder', deploy_id, service.name)
        env = self.get_env(deploy_id, service, slug_url)
        cmds = [
            'mkdir -p "%s"' % cache_dir,
            'cat {} | docker run -v {cache}:/tmp/cache:rw {env} -i -a stdin -a stdout elsdoerfer/slugbuilder {outuri}'.format(
                remote_temp, outuri=slug_url, cache=cache_dir,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()]),
            )
        ]
        self.e(run, ' && '.join(cmds))

        return slug_url

    def get_env(self, deploy_id, service, slug_url):
        # In addition to the service defined ENV, add some of our own.
        # These give the container access to service discovery
        env = {
           'APP_ID': deploy_id,
           'SLUG_URL': slug_url,
           'PORT': '8000',
           'SD_ARGS': 'exec -i eth0 {}:{}:{}'.format(deploy_id, service.name, 8000)
        }
        env.update(service.env)
        return env

    def deploy(self, deploy_id, service):
        if not 'git' in service:
            return

        slug_url = self.build(deploy_id, service)

        env = self.get_env(deploy_id, service, slug_url)

        deps = ['-d {}:{}:{}'.format(varname, deploy_id, sname)
                for sname, varname in service.get('expose', {}).items()]
        if deps:
            env['SD_ARGS'] = 'expose {deps} {cmd}'.format(
                deps=' '.join(deps),
                cmd='sdutil %s' % env['SD_ARGS']
            )

        self.host.deploy_docker_image(deploy_id, Service(service.name, {
            'image': 'elsdoerfer/slugrunner',
            'cmd': 'start {proc}'.format(proc=service.cmd),
            'env': env,
            'volumes': service.volumes,
            'from_file': service.from_file
        }), )

