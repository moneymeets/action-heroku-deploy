import json
import unittest
from unittest.mock import MagicMock, patch

from deploy_heroku import HerokuRelease, deploy_heroku_command, get_latest_commit_from_slug, \
    get_latest_heroku_release, get_payload_type, main, trigger_release_retry


class DeployHerokuTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.heroku_app = "fake-app"
        self.heroku_api_token = "fake-token"
        self.commit_hash = "abc1234"
        self.header = {
            "Accept": "application/vnd.heroku+json; version=3",
            "Authorization": "Bearer bar",
            "Content-Type": "application/json",
            "Range": "version ..; order=desc,max=10;",
        }

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_get_latest_heroku_release(self, mock_request, mock_urlopen):
        mock_data = ("c4eb8db5-53fe-411d-820c-9428c9ccad5f", 20, "succeeded", "Retry", "227c9e81-a699-9a1bea3b8119")
        release_id, release_version, release_status, description, slug_id = mock_data

        cm = MagicMock()
        cm.getcode.return_value, cm.read.return_value, cm.__enter__.return_value = (
            200,
            json.dumps(
                [
                    {
                        "id": release_id, "version": release_version, "status": release_status,
                        "description": description, "slug": {"id": slug_id},
                    },
                    {
                        "id": release_id, "version": release_version - 1, "status": release_status,
                        "description": description, "slug": {"id": slug_id},
                    },
                ],
            ),
            cm,
        )
        mock_urlopen.return_value = cm

        latest_release = get_latest_heroku_release("foo", "bar")
        mock_request.assert_called_once_with("https://api.heroku.com/apps/foo/releases", headers=self.header, data=None)

        self.assertEqual(latest_release.id, release_id)
        self.assertEqual(latest_release.version, release_version)
        self.assertEqual(latest_release.status, release_status)
        self.assertEqual(latest_release.description, description)
        self.assertEqual(latest_release.slug_id, slug_id)

    @patch("urllib.request.urlopen")
    def test_get_latest_heroku_release_fail(self, mock_urlopen):
        cm = MagicMock()
        cm.getcode.return_value, cm.__enter__.return_value = 403, cm
        mock_urlopen.return_value = cm

        self.assertRaises(AssertionError, get_latest_heroku_release, "foo", "bar")

    def test_deploy_heroku_command(self):
        expected_result = "git push https://heroku:bar@git.heroku.com/foobar.git sha:refs/heads/master"
        result = deploy_heroku_command("sha", "bar", "foobar", rollback=False)
        self.assertEqual(result, expected_result)

        expected_result = "git push https://heroku:bar@git.heroku.com/foobar.git sha:refs/heads/master --force"
        result = deploy_heroku_command("sha", "bar", "foobar", rollback=True)
        self.assertEqual(result, expected_result)

    def test_get_payload_type(self):
        result = get_payload_type(json.dumps({"ghd": {"type": "rollback"}}))
        self.assertEqual(result, "rollback")

        result = get_payload_type(json.dumps({"ghd": {"type": "redeploy"}}))
        self.assertEqual(result, "redeploy")

        result = get_payload_type("")
        self.assertEqual(result, None)

        self.assertRaises(KeyError, get_payload_type, json.dumps({"invalid_key": "invalid_value"}))

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_get_latest_commit_from_slug(self, mock_request, mock_urlopen):
        expected_commit = "adf4e5755802ad38136e2b0e09282568c4e30c22"

        cm = MagicMock()
        cm.getcode.return_value, cm.read.return_value, cm.__enter__.return_value = (
            200, json.dumps({"commit": expected_commit}), cm,
        )
        mock_urlopen.return_value = cm

        result_commit = get_latest_commit_from_slug("foo", "bar", "227c9e81-a699-9a1bea3b8119")
        mock_request.assert_called_once_with(
            "https://api.heroku.com/apps/foo/slugs/227c9e81-a699-9a1bea3b8119",
            headers=self.header, data=None,
        )

        self.assertEqual(result_commit, expected_commit)

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_trigger_release_retry(self, mock_request, mock_urlopen):
        mock_data = {
            "id": "c4eb8db5-53fe-411d-820c-9428c9ccad5f",
            "version": 20,
            "status": "succeeded",
            "description": "Retry",
        }

        cm = MagicMock()
        cm.getcode.return_value, cm.read.return_value, cm.__enter__.return_value = (
            201, json.dumps({**mock_data, "slug": {"id": "227c9e81-a699-9a1bea3b8119"}}), cm,
        )
        mock_urlopen.return_value = cm

        mock_heroku_release = HerokuRelease(**mock_data, slug_id="227c9e81-a699-9a1bea3b8119")

        result = trigger_release_retry("foo", "bar", mock_heroku_release)
        mock_request.assert_called_once_with(
            "https://api.heroku.com/apps/foo/releases",
            headers=self.header,
            data=json.dumps({
                "slug": mock_heroku_release.slug_id,
                "description": f"Retry of v{mock_heroku_release.version}: {mock_heroku_release.description}",
            }).encode(),
        )

        self.assertEqual(result.id, mock_heroku_release.id)
        self.assertEqual(result.version, mock_heroku_release.version)
        self.assertEqual(result.status, mock_heroku_release.status)
        self.assertEqual(result.description, mock_heroku_release.description)
        self.assertEqual(result.slug_id, mock_heroku_release.slug_id)

    def get_heroku_release(self, status: str) -> HerokuRelease:
        return HerokuRelease(
            slug_id="227c9e81-a699-9a1bea3b8119",
            **{
                "id": "c4eb8db5-53fe-411d-820c-9428c9ccad5f",
                "version": 20,
                "status": status,
                "description": "Retry",
            },
        )

    def test_main_release_fail(self):
        heroku_release = self.get_heroku_release("failed")

        with patch("deploy_heroku.get_payload_type", return_value="") as mock_payload, \
                patch("deploy_heroku.get_latest_heroku_release", return_value=heroku_release) as mock_get_release, \
                patch("deploy_heroku.get_latest_commit_from_slug", return_value="abc1234") as mock_get_commit, \
                patch("deploy_heroku.deploy_and_get_release", return_value=heroku_release) as mock_deploy:
            self.assertRaises(RuntimeError, main, self.heroku_app, self.heroku_api_token, self.commit_hash, "")

            mock_payload.assert_called_once_with("")
            mock_get_release.assert_called_once_with(self.heroku_app, self.heroku_api_token)
            mock_get_commit.assert_called_once_with(self.heroku_app, self.heroku_api_token, heroku_release.slug_id)
            mock_deploy.assert_called_once_with(
                self.heroku_app, self.heroku_api_token, self.commit_hash, rollback=False,
            )

    def test_main(self):
        heroku_release = self.get_heroku_release("succeeded")
        latest_commit = "abc1234"

        payload_rollback = json.dumps({"ghd": {"type": "rollback"}})
        with patch("deploy_heroku.get_payload_type", return_value="rollback") as mock_payload, \
                patch("deploy_heroku.get_latest_heroku_release", return_value=heroku_release) as mock_get_release, \
                patch("deploy_heroku.get_latest_commit_from_slug", return_value=latest_commit) as mock_get_commit, \
                patch("deploy_heroku.deploy_and_get_release", return_value=heroku_release) as mock_deploy:
            main(self.heroku_app, self.heroku_api_token, self.commit_hash, payload_rollback)
            mock_payload.assert_called_once_with(payload_rollback)
            mock_get_release.assert_called_once_with(self.heroku_app, self.heroku_api_token)
            mock_get_commit.assert_called_once_with(self.heroku_app, self.heroku_api_token, heroku_release.slug_id)
            mock_deploy.assert_called_once_with(self.heroku_app, self.heroku_api_token, self.commit_hash, rollback=True)

        payload_redeploy = json.dumps({"ghd": {"type": "redeploy"}})
        with patch("deploy_heroku.get_payload_type", return_value="redeploy") as mock_payload, \
                patch("deploy_heroku.get_latest_heroku_release", return_value=heroku_release) as mock_get_release, \
                patch("deploy_heroku.get_latest_commit_from_slug", return_value=latest_commit) as mock_get_commit, \
                patch("deploy_heroku.trigger_release_retry", return_value=heroku_release) as mock_trigger_release_retry:
            main(self.heroku_app, self.heroku_api_token, self.commit_hash, payload_redeploy)
            mock_payload.assert_called_once_with(payload_redeploy)
            mock_get_release.assert_called_once_with(self.heroku_app, self.heroku_api_token)
            mock_get_commit.assert_called_once_with(self.heroku_app, self.heroku_api_token, heroku_release.slug_id)
            mock_trigger_release_retry.assert_called_once_with(self.heroku_app, self.heroku_api_token, heroku_release)

        payload_empty = ""
        with patch("deploy_heroku.get_payload_type", return_value="") as mock_payload, \
                patch("deploy_heroku.get_latest_heroku_release", return_value=heroku_release) as mock_get_release, \
                patch("deploy_heroku.get_latest_commit_from_slug", return_value=latest_commit) as mock_get_commit, \
                patch("deploy_heroku.deploy_and_get_release", return_value=heroku_release) as mock_deploy:
            main(self.heroku_app, self.heroku_api_token, self.commit_hash, payload_empty)
            mock_payload.assert_called_once_with(payload_empty)
            mock_get_release.assert_called_once_with(self.heroku_app, self.heroku_api_token)
            mock_get_commit.assert_called_once_with(self.heroku_app, self.heroku_api_token, heroku_release.slug_id)
            mock_deploy.assert_called_once_with(
                self.heroku_app, self.heroku_api_token, self.commit_hash, rollback=False,
            )


if __name__ == "__main__":
    unittest.main()
