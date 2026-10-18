from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppendOnlyError(Exception):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError(f"{self.model.__name__} rows cannot be updated.")

    def delete(self):
        raise AppendOnlyError(f"{self.model.__name__} rows cannot be deleted.")


class AppendOnlyModel(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AppendOnlyError(f"{type(self).__name__} rows cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError(f"{type(self).__name__} rows cannot be deleted.")


class AuditEvent(AppendOnlyModel):
    field_changed = models.CharField(max_length=50)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def deleted(self):
        return self.filter(is_deleted=True)

    def delete(self):
        count = self.filter(is_deleted=False).update(is_deleted=True, deleted_at=timezone.now())
        return count, ({self.model._meta.label: count} if count else {})

    delete.alters_data = True
    delete.queryset_only = True

    def restore(self):
        return self.filter(is_deleted=True).update(is_deleted=False, deleted_at=None)

    restore.alters_data = True


AllRowsManager = models.Manager.from_queryset(SoftDeleteQuerySet)


class ActiveRowsManager(AllRowsManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveRowsManager()
    all_objects = AllRowsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        if self.is_deleted:
            return 0, {}
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])
        return 1, {self._meta.label: 1}

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])
