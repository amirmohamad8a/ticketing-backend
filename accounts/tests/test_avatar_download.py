import io
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests import read_streaming_body
from core.tests.factories import AdminFactory, AgentFactory, UserFactory

TEST_MEDIA_ROOT = tempfile.mkdtemp()
IMAGE_BYTES = b"avatar-bytes"


def _url(user):
    return f"/api/avatars/{user.id}/download/"


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "PNG")
    return SimpleUploadedFile("avatar.png", buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AvatarDownloadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def _with_avatar(self, user):
        user.avatar.save("avatar.png", ContentFile(IMAGE_BYTES), save=True)
        return user

    def setUp(self):
        self.customer = self._with_avatar(UserFactory())
        self.other_customer = self._with_avatar(UserFactory())
        self.agent = self._with_avatar(AgentFactory())
        self.admin = self._with_avatar(AdminFactory())
        self.agent_without_avatar = AgentFactory()

    def _get(self, viewer, owner):
        return _client_for(viewer).get(_url(owner))

    def test_unauthenticated_request_is_rejected(self):
        response = APIClient().get(_url(self.agent))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_access_rules_between_roles(self):
        cases = [
            (self.customer, self.customer, 200),
            (self.customer, self.other_customer, 404),
            (self.other_customer, self.customer, 404),
            (self.customer, self.agent, 200),
            (self.customer, self.admin, 200),
            (self.agent, self.customer, 200),
            (self.agent, self.other_customer, 200),
            (self.agent, self.admin, 200),
            (self.admin, self.customer, 200),
            (self.admin, self.agent, 200),
        ]
        for viewer, owner, expected in cases:
            with self.subTest(viewer=viewer.role, owner=owner.role, same=viewer == owner):
                response = self._get(viewer, owner)
                self.assertEqual(response.status_code, expected)
                if expected == 404:
                    self.assertEqual(response.data["error"]["code"], "not_found")

    def test_response_holds_a_url_and_its_lifetime(self):
        response = self._get(self.customer, self.agent)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"url", "expires_in"})
        self.assertGreater(response.data["expires_in"], 0)

    def test_link_streams_the_stored_image(self):
        link = self._get(self.agent, self.customer).data
        response = APIClient().get(link["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(read_streaming_body(response), IMAGE_BYTES)

    def test_user_without_an_avatar_returns_404(self):
        for viewer in (self.agent_without_avatar, self.admin, self.customer):
            with self.subTest(viewer=viewer.role):
                self.assertEqual(self._get(viewer, self.agent_without_avatar).status_code, 404)

    def test_unknown_user_returns_404(self):
        response = _client_for(self.admin).get("/api/avatars/999999/download/")
        self.assertEqual(response.status_code, 404)

    def test_only_get_is_allowed(self):
        response = _client_for(self.agent).post(_url(self.customer))
        self.assertEqual(response.status_code, 405)

    def test_link_of_a_replaced_avatar_stops_working(self):
        user = UserFactory()
        client = _client_for(user)
        client.patch("/api/auth/me/", {"avatar": _png()})
        old_link = client.get(_url(user)).data["url"]
        old_response = APIClient().get(old_link)
        self.assertEqual(old_response.status_code, 200)
        read_streaming_body(old_response)
        client.patch("/api/auth/me/", {"avatar": _png()})
        self.assertEqual(APIClient().get(old_link).status_code, 404)
        new_link = client.get(_url(user)).data["url"]
        new_response = APIClient().get(new_link)
        self.assertEqual(new_response.status_code, 200)
        read_streaming_body(new_response)


class AvatarDownloadSchemaTests(TestCase):
    def test_route_is_documented_under_the_avatars_tag(self):
        response = APIClient().get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        matching = [path for path in paths if path.startswith("/api/avatars/")]
        self.assertEqual(len(matching), 1)
        self.assertEqual(paths[matching[0]]["get"]["tags"], ["Avatars"])
