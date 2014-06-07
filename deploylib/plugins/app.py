import os
import subprocess
import tempfile

from . import Plugin, LocalPlugin
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

    def setup(self, service, definition):
        """Called when the plugin is asked to see if it should deploy
        the given service.
        """
        if not 'git' in definition['kwargs']:
            return False

        # Use the slug from the most recent deployed version.
        if not service.latest:
            # No code has been provided yet, put service in "hold" status.
            service.hold('app code not available', definition)
            # Communicate to the client it may upload the data
            # XXX ctx.warning('data-missing', service.name, 'git')
            return True

        self.deploy_slugrunner(
            service, definition, service.latest.app_version_id)
        return True

    def on_data_provided(self, service, files, data):
        """Data that this plugin has requested from the client
        has been uploaded.
        """
        if not 'app' in files:
            return

        # Use the held definition, or copy the latest one
        if service.held:
            definition = service.definition
        else:
            definition = service.latest.definition.copy()

        # Build into a slug
        uploaded_file = tempfile.mktemp()
        files['app'].save(uploaded_file)
        self.build(service, definition, uploaded_file, data['app']['version'])

        # Run this new version
        self.deploy_slugrunner(service, definition, data['app']['version'])

    def deploy_slugrunner(self, service, definition, slug_id):
        """Run the slug ``slug_id`` as a new version of ``service``
        using the service ``definition``.
        """

        slug_url = self._get_slug_url(service, slug_id)
        env = self._build_env(service, definition, slug_url)

        # Put together a rewritten service
        original_definition = definition
        definition = definition.copy()
        definition['env'].update(env)
        definition['image'] = 'flynn/slugrunner'
        definition['entrypoint'] = '/runner/init'
        definition['cmd'] = ['start'] + definition['cmd']
        # For compatibility with sdutil plugin - tell it where to find the binary
        definition['kwargs'].setdefault('sdutil', {})
        definition['kwargs']['sdutil']['binary'] = 'sdutil'

        self.host.create_container(service, definition)
        version = service.append_version(original_definition)
        version.app_version_id = slug_id

    def build(self, service, definition, filename, version):
        """Build an app using slugbuilder.

        Note: buildstep would give us a real exclusive image, rather than a
        container that presumably needs to unpack the slug every time. Maybe
        we could also commit the slugrunner container after the first run?
        """

        # Determine the url where we'll store the slug
        slug_url = self._get_slug_url(service, version)

        # To speed up the build, use a cache
        cache_dir = self.host.cache(
            'slugbuilder', service.deployment.id, service.name)

        # Run the slugbuilder
        docker = self.host.backend.client
        docker.pull('flynn/slugbuilder')
        env = self._build_env(service, definition, slug_url)

        # TODO: Sending data through stdin via the API isn't obvious
        # at all, so we'll fall back on the command line here for now.
        #container = docker.create_container(
        #    image='flynn/slugbuilder',
        #    stdin=filename,
        #    command=slug_url,
        #    environment=env,
        #    volumes={cache_dir: '/tmp/cache:rw'})
        builder_image = os.environ.get('SLUGBUILDER', 'flynn/slugbuilder')
        result = subprocess.check_output(
            'cat {} | docker run -u root -v {cache}:/tmp/cache:rw {env} -i -a stdin '
            '-a stdout {image} {outuri}'.format(
                filename, outuri=slug_url, cache=cache_dir,
                image=builder_image,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()])), shell=True)
        container_id = result.strip()

    def _get_slug_url(self, service, slug_name):
        # Put together an full url for a slug
        shelf_ip = self.host.discover('shelf')
        release_id = "{}/{}:{}".format(
            service.deployment.id, service.name, slug_name)
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))
        return slug_url

    @staticmethod
    def _build_env(service, definition, slug_url):
        # Put together some extra environment variables we know the
        # slugrunner image expects.
        env = {
           'APP_ID': service.deployment.id,
           'SLUG_URL': slug_url
        }
        env.update(definition['env'])
        return env


