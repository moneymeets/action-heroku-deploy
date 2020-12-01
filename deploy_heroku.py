import argparse
import dataclasses
import json
import os
import subprocess
import urllib.parse
import urllib.request
from http import HTTPStatus
from typing import Optional


class DeploymentType:
    ROLLBACK = "rollback"
    REDEPLOY = "redeploy"


class Endpoint:
    RELEASES = "releases"
    RELEASE = "releases/{}"
    SLUGS = "slugs/{}"


class HerokuStatus:
    PENDING = "pending"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


class HTTPMethod:
    GET = "GET"
    POST = "POST"
    PUT = "PUT"


@dataclasses.dataclass
class HerokuRelease:
    id: str
    version: int
    status: str
    description: str
    slug_id: str


def release_from_response(data) -> HerokuRelease:
    return HerokuRelease(
        **{prop.name: data[prop.name] for prop in dataclasses.fields(HerokuRelease) if prop.name != "slug_id"},
        slug_id=data["slug"]["id"],
    )


def get_status_codes(method: str) -> tuple:
    return {
        HTTPMethod.GET: (HTTPStatus.OK, HTTPStatus.PARTIAL_CONTENT),
        HTTPMethod.POST: (HTTPStatus.CREATED,),
    }[method]


def get_response(app: str, api_key: str, endpoint: str, payload: Optional[dict] = None):
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Range": "version ..; order=desc,max=10;",

    }

    request = urllib.request.Request(
        f"https://api.heroku.com/apps/{app}/{endpoint}",
        headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )

    with urllib.request.urlopen(request) as response:
        assert response.getcode() in get_status_codes(request.get_method()), response.getcode()
        return json.loads(response.read())


def get_latest_heroku_release(app: str, api_key: str) -> HerokuRelease:
    return release_from_response(get_response(app, api_key, Endpoint.RELEASES)[0])


def trigger_release_retry(app: str, api_key: str, release: HerokuRelease):
    payload = {"slug": release.slug_id, "description": f"Retry of v{release.version}: {release.description}"}
    return release_from_response(get_response(app, api_key, Endpoint.RELEASES, payload))




def deploy_heroku_command(commit_hash: str, api_key: str, app: str, rollback: bool) -> str:
    git_url = f"https://heroku:{api_key}@git.heroku.com/{app}.git"
    return f"git push {git_url} {commit_hash}:refs/heads/master {'--force' if rollback else ''}".strip()


def do_deploy(heroku_app: str, heroku_api_key: str, git_commit_hash: str, rollback: bool):
    deploy_command = deploy_heroku_command(git_commit_hash, heroku_api_key, heroku_app, rollback)
    subprocess.run(deploy_command, check=True, shell=True)


def main(heroku_app: str, heroku_api_key: str, git_commit_hash: str, payload_str: str):
    assert heroku_app and heroku_api_key and git_commit_hash, "app, API key and commit hash required!"

    print(f"Heroku app name: {heroku_app}")

    payload_type = json.loads(payload_str)["ghd"]["type"] if payload_str else None

    latest_release = get_latest_heroku_release(heroku_app, heroku_api_key)
    latest_slug = get_response(heroku_app, heroku_api_key, Endpoint.SLUGS.format(latest_release.slug_id))

    if latest_slug["commit"] == git_commit_hash and payload_type == DeploymentType.REDEPLOY:
        release_version = trigger_release_retry(heroku_app, heroku_api_key, latest_release).version
    elif payload_type == DeploymentType.ROLLBACK:
        do_deploy(heroku_app, heroku_api_key, git_commit_hash, rollback=True)
    else:
        do_deploy(heroku_app, heroku_api_key, git_commit_hash, rollback=False)

    latest_heroku_release = get_latest_heroku_release(heroku_app, heroku_api_key)
    if latest_heroku_release.status != HerokuStatus.SUCCEEDED:
        raise RuntimeError("Heroku release command failed! See Heroku release logs for detailed information.")

    print(f"New release version is {latest_heroku_release.version}")
    print(f"::set-output name=release_version::{latest_heroku_release.version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="perform deployment to Heroku")
    parser.add_argument("-a", "--app", default=os.environ.get("APP"), type=str)
    parser.add_argument("-K", "--api-key", default=os.environ.get("API_KEY"), type=str)
    parser.add_argument("-c", "--commit-hash", default=os.environ.get("COMMIT_HASH"), type=str)
    parser.add_argument("-p", "--payload", default=os.environ.get("EVENT_PAYLOAD"), type=str)
    args = parser.parse_args()

    main(args.app, args.api_key, args.commit_hash, args.payload)
