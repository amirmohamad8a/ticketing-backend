from rest_framework.pagination import CursorPagination


class TicketCursorPagination(CursorPagination):
    page_size = 20
    ordering = ("-created_at", "-id")
