from django.db import models


class Request(models.Model):
    """
    Hold requests from access.log files.
    """

    ip = models.GenericIPAddressField()
    timestamp = models.DateTimeField()
    status = models.PositiveSmallIntegerField()
    size = models.PositiveIntegerField()
    referer = models.CharField(max_length=2048, blank=True, null=True)
    user_agent = models.CharField(max_length=1024, blank=True, null=True)

    REQUEST_METHOD_CHOICES = [
        (1, "GET"),
        (2, "HEAD"),
        (3, "POST"),
        (4, "PUT"),
        (5, "PATCH"),
        (6, "DELETE"),
        (7, "OPTIONS"),
        (8, "CONNECT"),
        (8, "TRACE"),
    ]
    method = models.PositiveSmallIntegerField(choices=REQUEST_METHOD_CHOICES)

    path = models.CharField(max_length=1024)

    HTTP_PROTOCOL_CHOICES = [(1, "HTTP/1.0"), (2, "HTTP/1.1"), (3, "HTTP/2.0")]
    protocol = models.PositiveSmallIntegerField(choices=HTTP_PROTOCOL_CHOICES)

    def __str__(self):
        return f"{self.pk} {self.ip} {self.path}"
