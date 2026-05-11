import base64
import os
import unittest
from pathlib import Path


def basic_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


class GrimoraAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["GRIMORA_AUTH_USERNAME"] = "grimora"
        os.environ["GRIMORA_AUTH_PASSWORD"] = "super-secret"
        os.chdir(Path(__file__).resolve().parents[1])

        from fastapi.testclient import TestClient
        from src.app import app

        cls.client = TestClient(app)

    def test_missing_auth_is_rejected(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], 'Basic realm="Grimora"')

    def test_invalid_auth_is_rejected(self) -> None:
        response = self.client.get("/", headers=basic_header("grimora", "wrong-password"))

        self.assertEqual(response.status_code, 401)

    def test_valid_auth_is_allowed(self) -> None:
        response = self.client.get("/", headers=basic_header("grimora", "super-secret"))

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
