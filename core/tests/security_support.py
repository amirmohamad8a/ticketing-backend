import os
import shutil
import tempfile
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.tokens import issue_visitor_token
from core.tests.factories import (
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    SiteFactory,
    TicketFactory,
    VisitorFactory,
)

ORIGIN = "https://example.com"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n%%EOF"
SCRIPT_BYTES = b"#!/bin/sh\necho hello\n"


def client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def visitor_client(visitor, origin=ORIGIN, token=None):
    client = APIClient()
    headers = {"HTTP_X_VISITOR_TOKEN": token or issue_visitor_token(visitor)}
    if origin:
        headers["HTTP_ORIGIN"] = origin
    client.credentials(**headers)
    return client


def upload(content, name="note.txt", content_type="text/plain"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def use_temp_media(testcase):
    root = tempfile.mkdtemp()
    override = override_settings(MEDIA_ROOT=root)
    override.enable()
    testcase.addCleanup(override.disable)
    testcase.addCleanup(shutil.rmtree, root, ignore_errors=True)
    return root


def stored_files(root):
    return [
        os.path.join(directory, name)
        for directory, _subdirectories, names in os.walk(root)
        for name in names
    ]


def make_world(with_files=False):
    site = SiteFactory(allowed_origins=[ORIGIN])
    visitor_a = VisitorFactory(site=site)
    visitor_b = VisitorFactory(site=site)
    agent = AgentFactory()
    ticket_a = TicketFactory(from_visitor=True, visitor=visitor_a)
    ticket_b = TicketFactory(from_visitor=True, visitor=visitor_b)
    message_a = CommentFactory(ticket=ticket_a, author=None, visitor=visitor_a)
    note_a = CommentFactory(ticket=ticket_a, author=agent, is_internal=True)
    world = SimpleNamespace(
        site=site,
        agent=agent,
        visitor_a=visitor_a,
        visitor_b=visitor_b,
        ticket_a=ticket_a,
        ticket_b=ticket_b,
        message_a=message_a,
        note_a=note_a,
        file_a=None,
        note_file_a=None,
    )
    if with_files:
        world.file_a = AttachmentFactory(on_comment=True, comment=message_a, uploaded_by=None)
        world.note_file_a = AttachmentFactory(on_comment=True, comment=note_a, uploaded_by=agent)
    return world
