from drf_spectacular.utils import extend_schema, extend_schema_view

auth_schema = extend_schema_view(post=extend_schema(tags=["Auth"]))
