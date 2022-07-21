import json
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy_heroku import Endpoint, HTTPMethod, HerokuStatus, deploy_heroku_command, get_deployment_type, \
    get_latest_heroku_release, get_response, get_status_codes, main, release_from_response, trigger_release_retry, \
    wait_for_release, DeploymentType

MOCK_COMMIT_HASH = "abc1234"

MOCK_HEROKU_APP = "fake-app"
MOCK_HEROKU_API_TOKEN = "fake-token"

MOCK_HEADERS = {
    "Accept": "application/vnd.heroku+json; version=3",
    "Authorization": "Bearer fake-token",
    "Content-Type": "application/json",
    "Range": "version ..; order=desc,max=10;",
}
MOCK_RESPONSE = {
    "id": "c4eb8db5-53fe-411d-820c-9428c9ccad5f",
    "version": 19,
    "status": HerokuStatus.SUCCEEDED,
    "description": "Retry",
    "slug": {"id": "227c9e81-a699-9a1bea3b8119"},
}
MOCK_RELEASE = release_from_response(MOCK_RESPONSE)


class DeployHerokuTestCase(unittest.TestCase):
    def check_results(self, result):
        self.assertEqual(result.id, MOCK_RESPONSE["id"])
        self.assertEqual(result.version, MOCK_RESPONSE["version"])
        self.assertEqual(result.status, MOCK_RESPONSE["status"])
        self.assertEqual(result.description, MOCK_RESPONSE["description"])
        self.assertEqual(result.slug_id, MOCK_RESPONSE["slug"]["id"])

    def test_release_from_response(self):
        result = release_from_response(MOCK_RESPONSE)

        self.check_results(result)

    def test_get_status_codes(self):
        result = get_status_codes(HTTPMethod.GET)
        self.assertEqual(result, (HTTPStatus.OK, HTTPStatus.PARTIAL_CONTENT))

        result = get_status_codes(HTTPMethod.POST)
        self.assertEqual(result, (HTTPStatus.CREATED,))

        self.assertRaises(KeyError, get_status_codes, HTTPMethod.PUT)

    @patch("deploy_heroku.get_response", return_value=[MOCK_RESPONSE, {**MOCK_RESPONSE, "version": 20}])
    def test_get_latest_heroku_release(self, mock_get_response):
        result = get_latest_heroku_release(MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN)
        mock_get_response.assert_called_once_with("fake-app", "fake-token", "releases")

        self.check_results(result)

    @patch("urllib.request.urlopen")
    def test_get_response_unauthorized(self, mock_urlopen):
        cm = MagicMock()
        cm.getcode.return_value, cm.__enter__.return_value = HTTPStatus.FORBIDDEN, MagicMock()
        mock_urlopen.return_value = cm

        self.assertRaises(AssertionError, get_response, "foo", "bar", "releases")

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_get_response_post(self, mock_request, mock_urlopen):
        cm = MagicMock()
        cm.getcode.return_value, cm.read.return_value, cm.__enter__.return_value = (201, json.dumps(MOCK_RESPONSE), cm)
        mock_urlopen.return_value = cm

        mock_request.return_value.get_method.return_value = HTTPMethod.POST

        payload = {
            "slug": MOCK_RELEASE.slug_id,
            "description": f"Retry of v{MOCK_RELEASE.version}: {MOCK_RELEASE.description}",
        }

        result = get_response(MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN, Endpoint.RELEASES, payload)

        mock_request.assert_called_once_with(
            "https://api.heroku.com/apps/fake-app/releases",
            headers=MOCK_HEADERS,
            data=json.dumps(payload).encode(),
        )

        self.assertDictEqual(result, MOCK_RESPONSE)

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_get_response_get(self, mock_request, mock_urlopen):
        cm = MagicMock()
        cm.getcode.return_value, cm.read.return_value, cm.__enter__.return_value = (200, json.dumps(MOCK_RESPONSE), cm)
        mock_urlopen.return_value = cm

        mock_request.return_value.get_method.return_value = HTTPMethod.GET

        result = get_response(MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN, Endpoint.RELEASE.format(MOCK_RELEASE.version))

        mock_request.assert_called_once_with(
            "https://api.heroku.com/apps/fake-app/releases/19",
            headers=MOCK_HEADERS,
            data=None,
        )

        self.assertDictEqual(result, MOCK_RESPONSE)

    @patch("deploy_heroku.get_response", return_value=MOCK_RESPONSE)
    def test_trigger_release_retry(self, mock_get_response):
        result = trigger_release_retry(MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN, MOCK_RELEASE)
        payload = {"slug": result.slug_id, "description": f"Retry of v{result.version}: {result.description}"}
        mock_get_response.assert_called_once_with("fake-app", "fake-token", "releases", payload)

        self.check_results(result)

    @patch("deploy_heroku.get_response", side_effect=(
            {**MOCK_RESPONSE, "status": HerokuStatus.PENDING},
            {**MOCK_RESPONSE, "status": HerokuStatus.SUCCEEDED},
    ))
    def test_wait_for_release(self, mock_get_response):
        wait_for_release(MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN, 1, wait_time=1)
        mock_get_response.assert_called_with("fake-app", "fake-token", "releases/1")
        self.assertEqual(mock_get_response.call_count, 2)

    @patch("deploy_heroku.get_response", return_value={**MOCK_RESPONSE, "status": HerokuStatus.PENDING})
    def test_wait_for_release_timeout(self, mock_get_response):
        self.assertRaises(
            TimeoutError,
            wait_for_release,
            MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN, 1, timeout=1, wait_time=1,
        )
        mock_get_response.assert_called_once_with("fake-app", "fake-token", "releases/1")

    def test_deploy_heroku_command(self):
        expected_result = "git push https://heroku:bar@git.heroku.com/foobar.git sha:refs/heads/master"
        result = deploy_heroku_command("sha", "bar", "foobar", rollback=False)
        self.assertEqual(result, expected_result)

        expected_result = "git push https://heroku:bar@git.heroku.com/foobar.git sha:refs/heads/master --force"
        result = deploy_heroku_command("sha", "bar", "foobar", rollback=True)
        self.assertEqual(result, expected_result)

    def test_get_deployment_type(self):
        def test(payload: dict | str):
            with tempfile.NamedTemporaryFile(mode="w") as tmpfile:
                tmpfile.write(json.dumps(payload, indent=2))
                tmpfile.flush()
                self.assertEqual(get_deployment_type(Path(tmpfile.name)), DeploymentType.ROLLBACK)
                return get_deployment_type(Path(tmpfile.name))

        test({"deployment": {"payload": {"deployment_type": DeploymentType.ROLLBACK}}})
        test({"deployment": {"payload": json.dumps({"deployment_type": DeploymentType.ROLLBACK})}}),
        test({"deployment": {"payload": json.dumps({"ghd": {"type": DeploymentType.ROLLBACK}})}}),
        self.assertRaises(KeyError, test, {"bad_key": DeploymentType.ROLLBACK})

    def perform_test(self, rollback: bool, deployment_type: str):
        @patch("deploy_heroku.get_deployment_type", return_value=deployment_type)
        @patch("deploy_heroku.get_latest_heroku_release", return_value=MOCK_RELEASE)
        @patch("deploy_heroku.get_response", return_value={"commit": MOCK_COMMIT_HASH})
        @patch("deploy_heroku.do_deploy")
        @patch("deploy_heroku.trigger_release_retry", return_value=MOCK_RELEASE)
        @patch("deploy_heroku.wait_for_release", return_value=None)
        def run(mock_wait, mock_trigger_release, mock_deploy, mock_response, mock_get_release, mock_deployment_type):
            main(MOCK_HEROKU_APP, MOCK_HEROKU_API_TOKEN, MOCK_COMMIT_HASH, Path(""))
            mock_deployment_type.assert_called_with(Path(""))
            mock_get_release.assert_called_with("fake-app", "fake-token")
            mock_response.assert_called_with("fake-app", "fake-token", "slugs/227c9e81-a699-9a1bea3b8119")

            if deployment_type == "redeploy":
                mock_trigger_release.assert_called_with("fake-app", "fake-token", MOCK_RELEASE)
                mock_wait.assert_called_with("fake-app", "fake-token", MOCK_RELEASE.version)
            else:
                mock_deploy.assert_called_once_with("fake-app", "fake-token", "abc1234", rollback=rollback)

        run()

    def test_main_deploy(self):
        self.perform_test(rollback=False, deployment_type="forward")

    def test_main_redeploy(self):
        self.perform_test(rollback=False, deployment_type="redeploy")

    def test_main_rollback(self):
        self.perform_test(rollback=True, deployment_type=DeploymentType.ROLLBACK)

    def test_main_assert(self):
        self.assertRaises(AssertionError, main, "fake-app", "fake-token", "", "")
        self.assertRaises(AssertionError, main, "fake-app", "", "abc1234", "")
        self.assertRaises(AssertionError, main, "", "fake-token", "abc1234", "")


if __name__ == "__main__":
    unittest.main()
