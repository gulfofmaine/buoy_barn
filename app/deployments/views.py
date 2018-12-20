from django.shortcuts import get_object_or_404
from memoize import delete_memoized
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Platform
from .serializers import PlatformSerializer


class PlatformViewset(viewsets.ReadOnlyModelViewSet):
    """
    A viewset for viewing Platforms
    """
    queryset = Platform.objects.filter(active=True)
    serializer_class = PlatformSerializer

    def retrieve(self, request, pk=None):
        platform = get_object_or_404(self.queryset, name=pk)
        serializer = self.serializer_class(platform)
        return Response(serializer.data)
    
    @action(detail=False)
    def refresh(self, request):
        # delete_memoized('deployments.models.Platform.latest_erddap_values')
        delete_memoized(Platform.latest_erddap_values)

        serializer = self.get_serializer(self.queryset.all(), many=True)
        return Response(serializer.data)