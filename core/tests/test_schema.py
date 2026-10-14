import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIClient

from core.schema import HTTP_METHODS
from tickets.views import TicketViewSet

ERROR_REF = {"$ref": "#/components/schemas/Error"}
EXPECTED_TAGS = {
    "Auth",
    "Users",
    "Agents",
    "Avatars",
    "Tickets",
    "Attachments",
    "Canned replies",
    "Tags",
    "Sites",
    "Widget",
    "Realtime",
    "Stats",
    "Audit",
}
EXPECTED_PATHS = {
    "/api/agents/": "Agents",
    "/api/agents/online/": "Agents",
    "/api/attachments/{id}/download/": "Attachments",
    "/api/audit/": "Audit",
    "/api/auth/logout/": "Auth",
    "/api/auth/me/": "Auth",
    "/api/avatars/{id}/download/": "Avatars",
    "/api/canned-replies/": "Canned replies",
    "/api/canned-replies/{id}/": "Canned replies",
    "/api/sites/": "Sites",
    "/api/sites/{id}/rotate-key/": "Sites",
    "/api/stats/": "Stats",
    "/api/tags/": "Tags",
    "/api/tags/{id}/": "Tags",
    "/api/tickets/": "Tickets",
    "/api/tickets/export/": "Tickets",
    "/api/tickets/{id}/claim/": "Tickets",
    "/api/tickets/{id}/messages/": "Tickets",
    "/api/tickets/{id}/rating/": "Tickets",
    "/api/tickets/{id}/read/": "Tickets",
    "/api/users/": "Users",
    "/api/widget/config/": "Widget",
    "/api/widget/conversations/": "Widget",
    "/api/widget/conversations/{id}/rating/": "Widget",
    "/api/widget/ws/ticket/": "Widget",
    "/api/ws/ticket/": "Realtime",
}


def _operations(schema):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


class SchemaContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        response = APIClient().get("/api/schema/?format=json")
        assert response.status_code == 200
        cls.schema = response.json()

    def _query_names(self, path, method="get"):
        parameters = self.schema["paths"][path][method].get("parameters", [])
        return {item["name"] for item in parameters if item["in"] == "query"}

    def test_every_phase_15_route_is_documented_under_its_resource_tag(self):
        for path, tag in EXPECTED_PATHS.items():
            with self.subTest(path=path):
                self.assertIn(path, self.schema["paths"])
                for method, operation in self.schema["paths"][path].items():
                    if method in HTTP_METHODS:
                        self.assertEqual(operation["tags"], [tag])

    def test_every_operation_has_exactly_one_declared_tag(self):
        declared = {tag["name"] for tag in self.schema["tags"]}
        self.assertEqual(declared, EXPECTED_TAGS)
        for path, method, operation in _operations(self.schema):
            with self.subTest(path=path, method=method):
                self.assertEqual(len(operation["tags"]), 1)
                self.assertIn(operation["tags"][0], declared)

    def test_only_api_routes_are_published(self):
        for path in self.schema["paths"]:
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/api/"))
                self.assertFalse(path.startswith("/api/downloads/"))

    def test_operation_ids_are_unique(self):
        ids = [operation["operationId"] for _p, _m, operation in _operations(self.schema)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_error_response_uses_the_documented_envelope(self):
        for path, method, operation in _operations(self.schema):
            for code, response in operation["responses"].items():
                if code.isdigit() and int(code) >= 400:
                    with self.subTest(path=path, method=method, code=code):
                        content = response["content"]["application/json"]
                        self.assertEqual(content["schema"], ERROR_REF)

    def test_every_operation_documents_throttling(self):
        for path, method, operation in _operations(self.schema):
            with self.subTest(path=path, method=method):
                response = operation["responses"]["429"]
                self.assertIn("Retry-After", response["headers"])

    def test_the_error_envelope_components_exist(self):
        schemas = self.schema["components"]["schemas"]
        self.assertEqual(schemas["Error"]["required"], ["error"])
        self.assertEqual(schemas["ErrorBody"]["required"], ["code", "message", "details"])
        self.assertEqual(set(schemas["ErrorBody"]["properties"]), {"code", "message", "details"})

    def test_protected_routes_document_401_and_403(self):
        for path in ("/api/stats/", "/api/audit/", "/api/tickets/export/", "/api/sites/"):
            with self.subTest(path=path):
                responses = self.schema["paths"][path]["get"]["responses"]
                self.assertIn("401", responses)
                self.assertIn("403", responses)

    def test_both_security_schemes_are_declared(self):
        schemes = self.schema["components"]["securitySchemes"]
        self.assertEqual(schemes["jwtAuth"]["scheme"], "bearer")
        self.assertEqual(schemes["visitorToken"]["name"], "X-Visitor-Token")

    def test_the_ticket_list_documents_every_filter(self):
        expected = {"assignee", "cursor", "is_overdue", "priority", "search", "status", "tag"}
        self.assertTrue(expected <= self._query_names("/api/tickets/"))

    def test_the_export_documents_the_filters_and_returns_csv(self):
        expected = {"assignee", "is_overdue", "priority", "search", "status", "tag"}
        self.assertTrue(expected <= self._query_names("/api/tickets/export/"))
        content = self.schema["paths"]["/api/tickets/export/"]["get"]["responses"]["200"]["content"]
        self.assertIn("text/csv", content)

    def test_stats_and_audit_document_their_parameters(self):
        self.assertEqual(self._query_names("/api/stats/"), {"date_from", "date_to"})
        self.assertEqual(
            self._query_names("/api/audit/"),
            {"actor", "cursor", "date_from", "date_to", "field_changed", "kind"},
        )

    def test_the_rating_route_documents_both_methods_and_the_conflict(self):
        operations = self.schema["paths"]["/api/tickets/{id}/rating/"]
        self.assertIn("get", operations)
        self.assertIn("409", operations["post"]["responses"])

    def test_logout_has_a_request_serializer_and_no_response_body(self):
        operation = self.schema["paths"]["/api/auth/logout/"]["post"]
        body = operation["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(body, {"$ref": "#/components/schemas/LogoutRequest"})
        self.assertIn(
            "refresh", self.schema["components"]["schemas"]["LogoutRequest"]["properties"]
        )
        self.assertIn("205", operation["responses"])

    def test_the_description_points_to_the_realtime_document(self):
        self.assertIn("docs/realtime.md", self.schema["info"]["description"])


class SchemaGenerationTests(TestCase):
    def test_generation_prints_no_warnings_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "schema.yml"
            call_command(
                "spectacular",
                file=str(target),
                validate=True,
                fail_on_warn=True,
                stdout=StringIO(),
                stderr=StringIO(),
            )
            self.assertIn("openapi:", target.read_text(encoding="utf-8"))

    def test_the_ticket_viewset_is_safe_to_introspect_without_a_request(self):
        view = TicketViewSet()
        view.swagger_fake_view = True
        self.assertEqual(view.get_queryset().count(), 0)
