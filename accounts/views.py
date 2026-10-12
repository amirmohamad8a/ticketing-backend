from django.db import transaction
from django.utils.translation import gettext_lazy as _

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.models import User
from accounts.pagination import UserCursorPagination
from accounts.permissions import IsAdmin
from accounts.schema import auth_schema, password_change_schema, profile_schema, user_schema
from accounts.serializers import (
    PasswordChangeSerializer,
    ProfileSerializer,
    RegisterSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from accounts.tokens import blacklist_user_tokens


@auth_schema
class RegisterView(CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


@profile_schema
class MeView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


@password_change_schema
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user = serializer.save()
            blacklist_user_tokens(user)
            refresh = RefreshToken.for_user(user)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


@auth_schema
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            raise ValidationError({"refresh": _("Refresh token is required.")})
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            raise ValidationError({"refresh": _("Invalid or expired token.")})
        return Response(status=status.HTTP_205_RESET_CONTENT)


@auth_schema
class TaggedTokenObtainPairView(TokenObtainPairView):
    pass


@auth_schema
class TaggedTokenRefreshView(TokenRefreshView):
    pass


@user_schema
class UserViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["role", "is_active"]
    pagination_class = UserCursorPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action == "partial_update":
            return UserUpdateSerializer
        return UserSerializer
