import argparse
import dataclasses
import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Optional


@dataclasses.dataclass
class HerokuRelease:
    id: str
    version: int
    status: str
    description: str
    slug_id: str


class DeploymentType:
    ROLLBACK = "rollback"
    REDEPLOY = "redeploy"


class Endpoint:
    RELEASES = "releases"
    SLUGS = "slugs/{}"


def release_from_response(data) -> HerokuRelease:
    return HerokuRelease(
        **{prop.name: data[prop.name] for prop in dataclasses.fields(HerokuRelease) if prop.name != "slug_id"},
        slug_id=data["slug"]["id"],
    )


def get_request(app: str, api_key: str, endpoint: str, payload: Optional[dict] = None) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Range": "version ..; order=desc,max=10;",

    }

    return urllib.request.Request(
        f"https://api.heroku.com/apps/{app}/{endpoint}",
        headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )


def get_latest_commit_from_slug(app: str, api_key: str, slug_id: str):
    request = get_request(app, api_key, Endpoint.SLUGS.format(slug_id))

    with urllib.request.urlopen(request) as response:
        assert response.getcode() == 200, response.getcode()
        return json.loads(response.read())["commit"]


def get_latest_heroku_release(app: str, api_key: str) -> HerokuRelease:
    request = get_request(app, api_key, Endpoint.RELEASES)

    with urllib.request.urlopen(request) as response:
        assert response.getcode() in (200, 206), response.getcode()
        latest_release, *_ = json.loads(response.read())
        return release_from_response(latest_release)


def trigger_release_retry(app: str, api_key: str, release: HerokuRelease):
    request = get_request(
        app=app,
        api_key=api_key,
        endpoint=Endpoint.RELEASES,
        payload={"slug": release.slug_id, "description": f"Retry of v{release.version}: {release.description}"},
    )

    with urllib.request.urlopen(request) as response:
        assert response.getcode() == 201, response.getcode()
        return release_from_response(json.loads(response.read()))


def deploy_heroku_command(commit_hash: str, api_key: str, app: str, rollback: bool) -> str:
    git_url = f"https://heroku:{api_key}@git.heroku.com/{app}.git"
    return f"git push {git_url} {commit_hash}:refs/heads/master {'--force' if rollback else ''}".strip()


def deploy_and_get_release(heroku_app: str, heroku_api_key: str, git_commit_hash: str, rollback: bool) -> HerokuRelease:
    deploy_command = deploy_heroku_command(git_commit_hash, heroku_api_key, heroku_app, rollback)
    subprocess.run(deploy_command, check=True, shell=True)
    return get_latest_heroku_release(heroku_app, heroku_api_key)


def get_payload_type(payload: str) -> Optional[str]:
    return json.loads(payload)["ghd"]["type"] if payload else None


def main(heroku_app, heroku_api_key, git_commit_hash, payload_str):
    assert heroku_app and heroku_api_key and git_commit_hash, "app, API key and commit hash required!"

    print(f"Heroku app name: {heroku_app}")

    payload_type = get_payload_type(payload_str)

    latest_release = get_latest_heroku_release(heroku_app, heroku_api_key)
    commit_hash_from_slug = get_latest_commit_from_slug(heroku_app, heroku_api_key, latest_release.slug_id)
    if commit_hash_from_slug == git_commit_hash and payload_type == DeploymentType.REDEPLOY:
        latest_heroku_release = trigger_release_retry(heroku_app, heroku_api_key, latest_release)
    elif payload_type == DeploymentType.ROLLBACK:
        latest_heroku_release = deploy_and_get_release(heroku_app, heroku_api_key, git_commit_hash, rollback=True)
    else:
        latest_heroku_release = deploy_and_get_release(heroku_app, heroku_api_key, git_commit_hash, rollback=False)

    if latest_heroku_release.status != "succeeded":
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
