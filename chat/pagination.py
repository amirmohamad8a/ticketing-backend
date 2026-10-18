from rest_framework.pagination import CursorPagination


class SiteCursorPagination(CursorPagination):
    page_size = 20
    ordering = ("id",)
