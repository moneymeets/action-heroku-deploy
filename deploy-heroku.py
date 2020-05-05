#!/usr/bin/env python3
import subprocess
from dataclasses import dataclass
from typing import List

import click
import requests
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class HerokuRelease:
    id: str
    version: int
    status: str


def get_latest_heroku_release(app: str, api_key: str) -> HerokuRelease:
    response = requests.get(
        f"https://api.heroku.com/apps/{app}/releases",
        headers={
            "Accept": "application/vnd.heroku+json; version=3",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Range": "version ..; order=desc,max=10;",
        },
    )
    response.raise_for_status()

    latest_release, *_ = response.json()

    return HerokuRelease.from_dict(latest_release)


def deploy_heroku_command(commit_hash: str, api_key: str, app: str) -> List[str]:
    return ["git", "push", f"https://heroku:{api_key}@git.heroku.com/{app}.git", f"{commit_hash}:refs/heads/master"]


@click.group()
def main():
    pass


@main.command(name="deploy")
@click.option("-a", "--app", envvar="APP", required=True,
              help="Name of Heroku app. For example 'my-example-heroku-app'")
@click.option("-K", "--api-key", envvar="API_KEY", required=True,
              help="Heroku API Key")
@click.option("-c", "--commit-hash", envvar="COMMIT_HASH", required=True,
              help="Commit Hash. For example '59d2e89c36774ee3775050a437c290a6c1afb3db'")
@click.option("--dry-run/--no-dry-run", default=False, help="If set, skip deployment to Heroku")
def deploy(app: str, api_key: str, commit_hash: str, dry_run: bool):
    assert commit_hash

    click.echo(f"Heroku app name: {app}")

    old_release_version = get_latest_heroku_release(app, api_key).version
    click.echo(f"Old release version is {old_release_version}")

    deploy_command = deploy_heroku_command(app=app, api_key=api_key, commit_hash=commit_hash)

    subprocess.check_call(deploy_command) if not dry_run else click.echo(f"Dry run: {deploy_command}")

    latest_heroku_release = get_latest_heroku_release(app, api_key)


    click.echo(f"New release version is {latest_heroku_release.version}")
    print(f"::set-output name=release_version::{latest_heroku_release.version}")


if __name__ == "__main__":
    main()

