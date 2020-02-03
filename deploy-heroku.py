#!/usr/bin/env python3
import os
import subprocess
from typing import List

import click
import requests


def get_latest_heroku_release_version(app: str, api_key: str) -> int:
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
    return latest_release["version"]


def deploy_heroku_command(commit_hash: str, api_key: str, app: str) -> List[str]:
    return ["git", "push", f"https://heroku:{api_key}@git.heroku.com/{app}.git", f"{commit_hash}:refs/heads/master"]


def main():
    @click.command()
    @click.option("-a", "--app", envvar="APP", required=True,
                  help="Name of Heroku app. For example 'my-example-heroku-app'")
    @click.option("-K", "--api-key", envvar="API_KEY", required=True,
                  help="Heroku API Key")
    @click.option("-c", "--commit-hash", envvar="COMMIT_HASH", required=True,
                  help="Commit Hash. For example '59d2e89c36774ee3775050a437c290a6c1afb3db'")
    @click.option("--dry-run/--no-dry-run", default=False, help="If set, skip deployment to Heroku")
    def cli(app: str, api_key: str, commit_hash: str, dry_run: bool):
        assert commit_hash

        click.echo(f"Heroku app name: {app}")

        old_release_version = get_latest_heroku_release_version(app, api_key)
        click.echo(f"Old release version {old_release_version}")

        deploy_command = deploy_heroku_command(app=app, api_key=api_key, commit_hash=commit_hash)

        subprocess.check_call(deploy_command) if not dry_run else click.echo(f"{deploy_command}")

        new_release_version = get_latest_heroku_release_version(app, api_key)
        click.echo(f"New release version {new_release_version}")
        print(f"::set-output name=release_version::{new_release_version}")

    cli()


if __name__ == "__main__":
    main()

