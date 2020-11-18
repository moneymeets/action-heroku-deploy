import argparse
import dataclasses
import json
import os
import subprocess
import urllib.request
from typing import List


@dataclasses.dataclass
class HerokuRelease:
    id: str
    version: int
    status: str


def get_latest_heroku_release(app: str, api_key: str) -> HerokuRelease:
    request = urllib.request.Request(f"https://api.heroku.com/apps/{app}/releases")
    for key, value in (
            ("Accept", "application/vnd.heroku+json; version=3"),
            ("Authorization", f"Bearer {api_key}"),
            ("Content-Type", "application/json"),
            ("Range", "version ..; order=desc,max=10;"),
    ):
        request.add_header(key, value)

    with urllib.request.urlopen(request) as response:
        assert response.getcode() == 200, response.getcode()
        latest_release, *_ = json.loads(response.read())
        return HerokuRelease(**{prop.name: latest_release[prop.name] for prop in dataclasses.fields(HerokuRelease)})


def deploy_heroku_command(commit_hash: str, api_key: str, app: str) -> List[str]:
    return ["git", "push", f"https://heroku:{api_key}@git.heroku.com/{app}.git", f"{commit_hash}:refs/heads/master"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="perform deployment to Heroku")
    parser.add_argument("-a", "--app", default=os.environ.get("APP"), type=str)
    parser.add_argument("-K", "--api-key", default=os.environ.get("API_KEY"), type=str)
    parser.add_argument("-c", "--commit-hash", default=os.environ.get("COMMIT_HASH"), type=str)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    heroku_app, heroku_api_key, git_commit_hash = args.app, args.api_key, args.commit_hash
    assert heroku_app and heroku_api_key and git_commit_hash, "app, API key and commit hash required!"

    print(f"Heroku app name: {heroku_app}")

    old_release_version = get_latest_heroku_release(heroku_app, heroku_api_key).version
    print(f"Old release version is {old_release_version}")

    deploy_command = deploy_heroku_command(git_commit_hash, heroku_api_key, heroku_app)

    subprocess.run(deploy_command, check=True) if not args.dry_run else print(f"Dry run: {deploy_command}")

    latest_heroku_release = get_latest_heroku_release(heroku_app, heroku_api_key)

    if latest_heroku_release.status != "succeeded":
        raise RuntimeError("Heroku release command failed! See Heroku release logs for detailed information.")

    print(f"New release version is {latest_heroku_release.version}")
    print(f"::set-output name=release_version::{latest_heroku_release.version}")
