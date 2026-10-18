from drf_spectacular.drainage import warn
from drf_spectacular.extensions import OpenApiAuthenticationExtension

HTTP_METHODS = frozenset({"get", "put", "post", "patch", "delete", "head", "options", "trace"})
ERROR_SCHEMA_REF = "#/components/schemas/Error"
ERROR_BODY_SCHEMA_REF = "#/components/schemas/ErrorBody"
ERROR_DESCRIPTIONS = {
    "400": "The request is malformed or failed validation.",
    "401": "Authentication credentials are missing or invalid.",
    "403": "The caller is not allowed to perform this action.",
    "404": "The resource does not exist or is not visible to the caller.",
    "409": "The request conflicts with the current state of the resource.",
    "429": "Too many requests.",
}


class LoggedJWTScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.LoggedJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }


def _error_schemas():
    return {
        "Error": {
            "type": "object",
            "description": "The envelope of every failed request.",
            "properties": {"error": {"$ref": ERROR_BODY_SCHEMA_REF}},
            "required": ["error"],
        },
        "ErrorBody": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Stable machine readable code, for example `validation_error`.",
                },
                "message": {
                    "type": "string",
                    "description": "Human readable summary. Clients should not display it.",
                },
                "details": {
                    "nullable": True,
                    "description": (
                        "Field errors keyed by field name for a validation error, "
                        "`null` for every other error."
                    ),
                    "oneOf": [
                        {"type": "object", "additionalProperties": {}},
                        {"type": "array", "items": {}},
                    ],
                },
            },
            "required": ["code", "message", "details"],
        },
    }


def _error_content():
    return {"application/json": {"schema": {"$ref": ERROR_SCHEMA_REF}}}


def _error_response(code):
    response = {"description": ERROR_DESCRIPTIONS[code], "content": _error_content()}
    if code == "429":
        response["headers"] = {
            "Retry-After": {
                "description": "Seconds to wait before sending the request again.",
                "schema": {"type": "integer"},
            }
        }
    return response


def _error_codes(path, operation):
    codes = {"429"}
    parameters = operation.get("parameters", [])
    if "requestBody" in operation or any(item.get("in") == "query" for item in parameters):
        codes.add("400")
    security = operation.get("security")
    public = security == [{}]
    if not public:
        codes.add("401")
    if security and not public:
        codes.add("403")
    if "{" in path:
        codes.add("404")
    return codes


def add_error_responses(result, generator, request, public):
    components = result.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.update(_error_schemas())
    components["schemas"] = dict(sorted(schemas.items()))
    for path, item in result.get("paths", {}).items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            if not operation.get("tags"):
                warn(f"{method.upper()} {path} has no tag.")
            responses = operation.setdefault("responses", {})
            for code in _error_codes(path, operation):
                responses.setdefault(code, _error_response(code))
            for code, response in responses.items():
                if code.isdigit() and int(code) >= 400 and "content" not in response:
                    response["content"] = _error_content()
            operation["responses"] = dict(sorted(responses.items()))
    return result
