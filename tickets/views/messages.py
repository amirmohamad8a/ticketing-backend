from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from tickets.messages import MESSAGES_PAGE_SIZE, message_page, post_customer_message, post_message
from tickets.participants import Participant
from tickets.reads import visible_comments
from tickets.schema import comments_schema
from tickets.serializers import CommentSerializer, MessageListSerializer, MessageQuerySerializer


class MessagesMixin:
    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        ticket = self.get_object()
        query = MessageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        after = query.validated_data["after"]
        before = query.validated_data.get("before")
        participant = Participant.from_request(request)
        queryset = visible_comments(ticket, participant).select_related("author")
        rows, has_more = message_page(queryset, after, MESSAGES_PAGE_SIZE, before)
        payload = {
            "results": rows,
            "has_more": has_more,
            "unread_count": ticket.unread_count,
        }
        return Response(MessageListSerializer(payload, context={"request": request}).data)

    @comments_schema
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def comments(self, request, pk=None):
        ticket = self.get_object()

        if request.method == "GET":
            queryset = ticket.comments.select_related("author")
            if not Participant.from_request(request).sees_internal_notes:
                queryset = queryset.filter(is_internal=False)
            latest = list(queryset.order_by("-id")[: MESSAGES_PAGE_SIZE + 1])
            has_more = len(latest) > MESSAGES_PAGE_SIZE
            rows = sorted(latest[:MESSAGES_PAGE_SIZE], key=lambda comment: comment.id)
            response = Response(CommentSerializer(rows, many=True).data)
            if has_more:
                response["X-Results-Truncated"] = "true"
            return response

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        is_internal = data.get("is_internal", False)
        participant = Participant.from_request(request)
        if participant.is_customer:
            comment, created = post_customer_message(
                ticket,
                data["body"],
                participant,
                is_internal=False,
                client_msg_id=data.get("client_msg_id"),
            )
        else:
            comment, created = post_message(
                ticket,
                data["body"],
                participant,
                is_internal=is_internal,
                client_msg_id=data.get("client_msg_id"),
            )
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(CommentSerializer(comment).data, status=status_code)
