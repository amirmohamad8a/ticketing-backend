def attachment_files():
    from tickets.models import Attachment

    return Attachment.objects.values_list("file", flat=True)
