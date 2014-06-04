import os
from subprocess import check_output as run
import tempfile

from . import Plugin, LocalPlugin, DataMissing
from deploylib.daemon.host import ServiceDef
from deploylib.client.utils import directory


class LocalAppPlugin(LocalPlugin):
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

        # Take the slug that we have already built, from the last deployed
        # version of the service (deployed  via this upload, or by git push).
        # If there is no such slug, that means this is a new service, and
        # we need to ask the client to provide the code.
        sinfo = self.host.db.deployments[deploy_id].services[service.name]
        if not sinfo.latest or not getattr(sinfo.latest, 'app_version_id', None):
            sinfo._definition = service
            raise DataMissing(service.name, 'git')

        slug_url = self._get_slug_url(
            deploy_id, service.name, sinfo.latest.app_version_id)
        self.deploy_slugrunner(deploy_id, service, slug_url)
        return True

    def deploy_slugrunner(self, deploy_id, service, slug_url):
        """Run the given slug.
        """

        env = self._build_env(deploy_id, service, slug_url)

        # Put together a rewritten service
        service = service.copy()
        service['env'].update(env)
        service['image'] = 'flynn/slugrunner'
        service['entrypoint'] = '/runner/init'
        service['cmd'] = ['start'] + service['cmd']
        # For compatibility with sdutil plugin - tell it where to find the binary
        service['kwargs'].setdefault('sdutil', {})
        service['kwargs']['sdutil']['binary'] = 'sdutil'

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
           'SLUG_URL': slug_url
        }
        env.update(service['env'])
        return env

    def on_data_provided(self, deploy_id, service_name, files, data):
        """Data that this plugin has requested from the client
        has been provided.
        """
        if not 'app' in files:
            return

        deployment = self.host.db.deployments[deploy_id]

        service = ServiceDef(service_name,
            deployment.services[service_name]._definition)
        service.globals = deployment.globals

        # Built into a slug
        uploaded_file = tempfile.mktemp()
        files['app'].save(uploaded_file)
        slug_url = self.build(deploy_id, service, uploaded_file, data['app']['version'])

        # Create a new version of the service
        version = deployment.services[service_name].append_version(service)
        version.app_version_id = data['app']['version']

        # Run this new version
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
        builder_image = os.environ.get('SLUGBUILDER', 'flynn/slugbuilder')
        result = run('cat {} | docker run -u root -v {cache}:/tmp/cache:rw {env} -i -a stdin '
            '-a stdout {image} {outuri}'.format(
                filename, outuri=slug_url, cache=cache_dir,
                image=builder_image,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()])), shell=True)
        container_id = result.strip()

        return slug_url


