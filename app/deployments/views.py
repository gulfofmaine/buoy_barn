from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.response import Response

from .models import Platform
from .serializers import PlatformSerializer


class PlatformViewset(viewsets.ReadOnlyModelViewSet):
    """
    A viewset for viewing Platforms
    """
    queryset = Platform.objects.all()
    serializer_class = PlatformSerializer

    def retrieve(self, request, pk=None):
        platform = get_object_or_404(self.queryset, name=pk)
        serializer = PlatformSerializer(platform)
        return Response(serializer.data)
