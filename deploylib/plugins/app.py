from subprocess import check_output as run
import tempfile

from . import Plugin, DataMissing
from deploylib.daemon.host import Service
from deploylib.client.utils import directory


class LocalPlugin(object):
    """Base interface for a plugin that runs as part of the CLI
    on the client.
    """

    def provide_data(self, service, what):
        """Server says it is missing data for the given service.

        This should return a dict of files that will be uploaded.
        """
        if what != 'git':
            return False

        # The given path may be a subdirectory of a repo
        # For git archive to work right we need the sub path relative
        # to the repository root.
        project_path = service.path(service['git'])
        with directory(project_path):
            git_root = run('git rev-parse --show-toplevel', shell=True)
            gitsubdir = project_path[len(git_root):]

        # Determine git version
        with directory(project_path):
            app_version = run('git rev-parse HEAD', shell=True)[:10]

        # Create and push the git archive
        with directory(project_path):
            temp = tempfile.mktemp()
            run('git archive HEAD:{} > {}'.format(gitsubdir, temp), shell=True)

            return {
                'app': (temp, {'version': app_version})
            }



class AppPlugin(Plugin):
    """Will run a 12-factor style app.
    """

    def setup(self, deploy_id, service):
        """Called when the plugin is asked to see if it should deploy
        the given service.
        """
        if not 'git' in service['kwargs']:
            return False

        # Check we have a release to deploy, otherwise ask the client to
        # upload one now.
        sinfo = self.host.state['deployments'][deploy_id][service.name]
        slug_name = sinfo.get('app', {}).get('url')
        if not slug_name:
            raise DataMissing(service.name, 'git')

        slug_url = self._get_slug_url(deploy_id, service.name, slug_name)
        self.deploy_slugrunner(deploy_id, service, slug_url)
        return True

    def deploy_slugrunner(self, deploy_id, service, slug_url):
        """Run the given slug.
        """

        env = self._build_env(deploy_id, service, slug_url)

        # Inject all required dependencies
        deps = ['-d {}:{}:{}'.format(varname, deploy_id, sname)
                for sname, varname in service.get('expose', {}).items()]
        if deps:
            env['SD_ARGS'] = 'expose {deps} {cmd}'.format(
                deps=' '.join(deps),
                cmd='sdutil %s' % env['SD_ARGS']
            )

        # Put together a rewritten service
        service = service.copy()
        service['env'].update(env)
        service['image'] = 'flynn/slugrunner'
        service['cmd'] = 'start {proc}'.format(proc=service['cmd'])

        self.host.deploy_docker_image(deploy_id, service)

    def _get_slug_url(self, deploy_id, service_name, slug_name):
        # Put together an full url for a slug
        shelf_ip = self.host.discover('shelf')
        release_id = "{}/{}:{}".format(deploy_id, service_name, slug_name)
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))
        return slug_url

    @staticmethod
    def _build_env(deploy_id, service, slug_url):
        # Put together some extra environment variables we know the
        # slugrunner image expects.
        env = {
           'APP_ID': deploy_id,
           'SLUG_URL': slug_url,
           'PORT': '8000',
           'SD_ARGS': 'exec -i eth0 -s {}:{}:{}'.format(deploy_id, service.name, 8000)
        }
        env.update(service['env'])
        return env

    def on_data_provided(self, deploy_id, service_name, files, data):
        if not 'app' in files:
            return

        service = Service(service_name,
            self.host.state['deployments'][deploy_id][service_name]['definition'])
        service.globals = self.host.state['deployments'][deploy_id].get('globals')

        uploaded_file = tempfile.mktemp()
        files['app'].save(uploaded_file)

        slug_url = self.build(deploy_id, service, uploaded_file, data['app']['version'])
        self.deploy_slugrunner(deploy_id, service, slug_url)

    def build(self, deploy_id, service, filename, version):
        """Build an app using slugbuilder.

        Note: buildstep would give us a real exclusive image, rather than a
        container that presumably needs to unpack the slug every time. Maybe
        we could also commit the slugrunner container after the first run?
        """

        # Determine the url where we'll store the slug
        slug_name = version
        slug_url = self._get_slug_url(deploy_id, service.name, slug_name)

        # To speed up the build, use a cache
        cache_dir = self.host.cache('slugbuilder', deploy_id, service.name)

        # Run the slugbuilder
        docker = self.host.client
        docker.pull('flynn/slugbuilder')
        env = self._build_env(deploy_id, service, slug_url)

        # TODO: Sending data through stdin via the API isn't obvious
        # at all, so we'll fall back on the command line here for now.
        #container = docker.create_container(
        #    image='flynn/slugbuilder',
        #    stdin=filename,
        #    command=slug_url,
        #    environment=env,
        #    volumes={cache_dir: '/tmp/cache:rw'})
        result = run('cat {} | docker run -v {cache}:/tmp/cache:rw {env} -i -a stdin '
            '-a stdout flynn/slugbuilder {outuri}'.format(
                filename, outuri=slug_url, cache=cache_dir,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()])), shell=True)
        container_id = result.strip()

        return slug_url


