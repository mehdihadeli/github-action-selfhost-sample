import json
import os
import pathlib
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


def is_ready(application, revision, image):
    status = application.get('status', {})
    sync = status.get('sync', {})
    return (
        sync.get('revision') == revision
        and sync.get('status') == 'Synced'
        and status.get('health', {}).get('status') == 'Healthy'
        and image in status.get('summary', {}).get('images', [])
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, 'Redirect refused', headers, response)


def main():
    server = urllib.parse.urlsplit(os.environ['ARGO_SERVER'])
    allow_http = os.environ.get('ARGO_ALLOW_HTTP') == 'true'
    if (server.scheme not in (['https', 'http'] if allow_http else ['https'])
            or not server.hostname or server.username or server.password or server.query or server.fragment):
        raise SystemExit('Argo CD requires a valid HTTPS base URL without embedded credentials.')
    revision = os.environ['ARGO_REVISION']
    image = os.environ['ARGO_IMAGE']
    token = os.environ['ARGO_TOKEN']
    application = os.environ['ARGO_APP']
    timeout = int(os.environ.get('ARGO_TIMEOUT', '900'))
    if (not token or not re.fullmatch(r'[a-f0-9]{40}', revision)
            or not re.fullmatch(r'.+@sha256:[a-f0-9]{64}', image)
            or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', application)
            or not 1 <= timeout <= 1800):
        raise SystemExit('Invalid Argo CD token, application, revision, image, or timeout configuration.')
    context = ssl.create_default_context(cafile=os.environ.get('ARGO_CA') or None)
    client = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    endpoint = os.environ['ARGO_SERVER'].rstrip('/') + '/api/v1/applications/' + application + '?refresh=normal'
    deadline = time.monotonic() + timeout
    directory = pathlib.Path('artifacts/runtime')
    directory.mkdir(parents=True, exist_ok=True)
    while time.monotonic() < deadline:
        request = urllib.request.Request(endpoint, headers={'Authorization': 'Bearer ' + token})
        try:
            with client.open(request, timeout=min(20, max(1, deadline - time.monotonic()))) as response:
                state = json.load(response)
            status = state.get('status', {})
            evidence = {
                'application': application, 'expectedRevision': revision, 'expectedImage': image,
                'sync': status.get('sync', {}), 'health': status.get('health', {}),
                'images': status.get('summary', {}).get('images', []),
            }
            (directory / 'argocd.json').write_text(json.dumps(evidence, indent=2) + '\n')
            if is_ready(state, revision, image):
                print('Argo CD is Synced and Healthy at the exact promoted revision and image.')
                return
        except urllib.error.HTTPError as error:
            if error.code < 500:
                raise SystemExit(f'Argo CD API rejected the request: HTTP {error.code}.') from None
        except urllib.error.URLError:
            print('Argo CD API temporarily unavailable; retrying within deadline.')
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise SystemExit('Argo CD did not reconcile the exact revision/image within the deadline.')


if __name__ == '__main__':
    main()