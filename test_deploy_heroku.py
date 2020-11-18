import json
import unittest
from unittest.mock import MagicMock, call, patch

from deploy_heroku import deploy_heroku_command, get_latest_heroku_release


class DeployHerokuTestCase(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_get_latest_heroku_release(self, mock_request, mock_urlopen):
        release_id, release_version, release_status = ("c4eb8db5-53fe-411d-820c-9428c9ccad5f", 20, "succeeded")

        cm = MagicMock()
        cm.getcode.return_value, cm.read.return_value, cm.__enter__.return_value = (
            200,
            json.dumps(
                [
                    {"id": release_id, "version": release_version, "status": release_status},
                    {"id": release_id, "version": release_version - 1, "status": release_status},
                ],
            ),
            cm,
        )
        mock_urlopen.return_value = cm

        latest_release = get_latest_heroku_release("foo", "bar")

        mock_request.assert_called_once_with("https://api.heroku.com/apps/foo/releases")
        mock_request().add_header.assert_has_calls([call("Authorization", "Bearer bar")], any_order=True)

        self.assertEqual(latest_release.id, release_id)
        self.assertEqual(latest_release.version, release_version)
        self.assertEqual(latest_release.status, release_status)

    @patch("urllib.request.urlopen")
    def test_get_latest_heroku_release_fail(self, mock_urlopen):
        cm = MagicMock()
        cm.getcode.return_value, cm.__enter__.return_value = 403, cm
        mock_urlopen.return_value = cm

        self.assertRaises(AssertionError, get_latest_heroku_release, "foo", "bar")

    def test_deploy_heroku_command(self):
        expected_result = ["git", "push", "https://heroku:bar@git.heroku.com/foobar.git", "sha:refs/heads/master"]
        result = deploy_heroku_command("sha", "bar", "foobar")
        self.assertEqual(result, expected_result)


if __name__ == "__main__":
    unittest.main()
