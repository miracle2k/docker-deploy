"""Runs 12-factor apps from git using flynn/slugrunner.

Will automatically install flynn/shelf as part of tye system deployment to
store compiled slugs.
"""

import os
import subprocess
import tempfile

from . import Plugin, LocalPlugin
import yaml
from deploylib.daemon.context import ctx
from deploylib.daemon.controller import DeployError


class LocalAppPlugin(LocalPlugin):
    """Base interface for a plugin that runs as part of the CLI
    on the client.
    """

    def provide_data(self, service, what):
        """Server says it is missing data for the given service.

        This should return a dict of files that will be uploaded.
        """
        run = subprocess.check_output
        from deploylib.client.utils import directory

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


SHELF = """
image: elsdoerfer/shelf
cmd: -s /var/lib/shelf
volumes: {data: /var/lib/shelf}
"""


class AppPlugin(Plugin):
    """Will run a 12-factor style app.
    """

    priority = 50

    def setup(self, service, version):
        if not 'git' in version.definition['kwargs']:
            return False

        # If the shelf service has not yet been setup, do so now
        if not 'shelf' in ctx.cintf.db.deployments['system'].services:
            shelf_def = yaml.load(SHELF)
            ctx.cintf.set_service('system', 'shelf', shelf_def, force=True)

        # If this service version has no slug id attached, hold it back
        # for now and ask the client to provide the code.
        if not version.data.get('app_version_id'):
            # No code has been provided yet, put service in "hold" status.
            service.hold('app code not available', version)
            # Communicate to the client it may upload the data
            ctx.custom(**{'data-request': service.name, 'tag': 'git'})
            return True

    def on_data_provided(self, service, files, data):
        """Client has uploaded the app code.
        """
        if not 'app' in files:
            return

        # Use the held version, or copy the latest one
        if service.held:
            version = service.held_version
        else:
            version = service.derive()
        version.data['app_version_id'] = data['app']['version']

        ctx.job('building slug for %s, version %s' % (
            service.name, data['app']['version']))

        # Build into a slug
        uploaded_file = tempfile.mktemp()
        files['app'].save(uploaded_file)
        self.build(service, version, uploaded_file)

        # Run this new version
        ctx.cintf.setup_version(service, version)

    def rewrite_service(self, service, version, definition):
        """Convert service to be run as a slugrunner.
        """
        if not 'git' in version.definition['kwargs']:
            return False

        env = self._build_env(service, version)

        # Put together a rewritten service
        definition['env'].update(env)
        definition['image'] = 'flynn/slugrunner'
        definition['entrypoint'] = '/runner/init'
        definition['cmd'] = ['start'] + definition['cmd']
        # For compatibility with sdutil plugin - tell it where to find the
        # binary. Note that slugrunner has support for sdutil builtin,
        # enabled by setting the SD_NAME variable. We do not use this support
        # and instead use the sdutil plugin do its thing.
        definition['kwargs'].setdefault('sdutil', {})
        definition['kwargs']['sdutil']['binary'] = 'sdutil'

    def build(self, service, version, filename):
        """Build an app using slugbuilder.

        Note: buildstep would give us a real exclusive image, rather than a
        container that presumably needs to unpack the slug every time. Maybe
        we could also commit the slugrunner container after the first run?
        """

        # Determine the url where we'll store the slug
        slug_url = self._get_slug_url(service, version.data['app_version_id'])

        # To speed up the build, use a cache
        cache_dir = ctx.cintf.cache(
            'slugbuilder', service.deployment.id, service.name)

        # Run the slugbuilder
        docker = ctx.cintf.backend.client
        docker.pull('flynn/slugbuilder')
        env = self._build_env(service, version)

        # TODO: Sending data through stdin via the API isn't obvious
        # at all, so we'll fall back on the command line here for now.
        #container = docker.create_container(
        #    image='flynn/slugbuilder',
        #    stdin=filename,
        #    command=slug_url,
        #    environment=env,
        #    volumes={cache_dir: '/tmp/cache:rw'})
        builder_image = os.environ.get('SLUGBUILDER', 'flynn/slugbuilder')

        cmd = ('cat {} | docker run -u root -v {cache}:/tmp/cache:rw {env} -i -a stdin '
              '-a stdout {image} {outuri}'.format(
                filename, outuri=slug_url, cache=cache_dir,
                image=builder_image,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()])))

        build_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, bufsize=0)

        line = build_process.stdout.readline()
        while line:
            if line.startswith('\x1b'):
                # There is some type of shell code at the beginning, and
                # it somehow prevents indentation.
                line = line[4:]
            ctx.log(line.strip())
            line = build_process.stdout.readline()

        if build_process.returncode:
            raise DeployError('the build failed with code %s' % build_process.returncode)

    def _get_slug_url(self, service, slug_name):
        # Put together an full url for a slug
        shelf_ip = ctx.cintf.discover('shelf')
        release_id = "{}/{}:{}".format(
            service.deployment.id, service.name, slug_name)
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))
        return slug_url

    def _build_env(self, service, version):
        # Put together some extra environment variables we know the
        # slugrunner image expects.
        env = {
           'APP_ID': service.deployment.id,
           'SLUG_URL': self._get_slug_url(service, version.data['app_version_id'])
        }
        env.update(version.definition['env'])
        return env


