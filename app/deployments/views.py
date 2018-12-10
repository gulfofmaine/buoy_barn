from django.http import Http404
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Platform
from .serializers import PlatformSerializer


class PlatformList(generics.ListAPIView):
    queryset = Platform.objects.all()
    serializer_class = PlatformSerializer


# class PlatformDetail(generics.RetrieveAPIView):
#     queryset = Platform.objects.all()
#     serializer_class = PlatformSerializer

class PlatformDetail(APIView):
    def get_object(self, pk):
        try:
            return Platform.objects.get(name=pk)
        except Platform.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):
        platform = self.get_object(pk)
        serializer = PlatformSerializer(platform)
        return Response(serializer.data)
