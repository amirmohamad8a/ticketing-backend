from rest_framework.pagination import CursorPagination


class UserCursorPagination(CursorPagination):
    page_size = 20
    ordering = ("id",)
