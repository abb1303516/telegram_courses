import re
import unittest

from app import app
from config import Config


class SecurityTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def _csrf(self, ip: str = "127.0.0.1") -> str:
        response = self.client.get("/login", environ_base={"REMOTE_ADDR": ip})
        match = re.search(
            rb'name="csrf_token" value="([^"]+)"',
            response.data,
        )
        self.assertIsNotNone(match)
        return match.group(1).decode("ascii")

    def test_security_headers(self):
        response = self.client.get("/login", base_url="https://173.249.194.240")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Strict-Transport-Security"], "max-age=31536000")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_api_post_without_csrf_is_rejected(self):
        response = self.client.post("/api/course/download", json={})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()["ok"])

    def test_login_and_logout_require_csrf(self):
        ip = "127.0.0.2"
        token = self._csrf(ip)
        response = self.client.post(
            "/login",
            data={"password": Config.APP_PASSWORD, "csrf_token": token},
            environ_base={"REMOTE_ADDR": ip},
        )
        self.assertEqual(response.status_code, 302)

        self.assertEqual(self.client.get("/logout").status_code, 405)
        with self.client.session_transaction() as user_session:
            logout_token = user_session["_csrf_token"]
        response = self.client.post(
            "/logout",
            data={"csrf_token": logout_token},
            environ_base={"REMOTE_ADDR": ip},
        )
        self.assertEqual(response.status_code, 302)

    def test_failed_logins_are_rate_limited(self):
        ip = "127.0.0.3"
        token = self._csrf(ip)
        for _ in range(5):
            response = self.client.post(
                "/login",
                data={"password": "definitely-wrong", "csrf_token": token},
                environ_base={"REMOTE_ADDR": ip},
            )
            self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/login",
            data={"password": "definitely-wrong", "csrf_token": token},
            environ_base={"REMOTE_ADDR": ip},
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Слишком много попыток".encode("utf-8"), response.data)

    def test_tojson_escapes_javascript_string_breakout(self):
        template = app.jinja_env.from_string("{{ value|tojson }}")
        rendered = template.render(value="lesson');alert(1)//.mp4")
        self.assertNotIn("'", rendered)
        self.assertIn("\\u0027", rendered)


if __name__ == "__main__":
    unittest.main()
