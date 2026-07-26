from django.http import JsonResponse
from django.views import View
from django.views.decorators.http import require_http_methods
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from sample_app.models import Book

# 1. Standard Decorated FBV
@require_http_methods(["GET", "POST"])
def book_list_fbv(request):
    books = Book.objects.all()
    # Intentionally flawed N+1 access pattern
    data = [{"id": b.id, "title": b.title, "author": b.author.name} for b in books]
    return JsonResponse(data, safe=False)

# 2. Django Class-Based View (CBV)
class BookDetailCBV(View):
    def get(self, request, pk):
        book = Book.objects.get(pk=pk)
        return JsonResponse({"id": book.id, "title": book.title, "author": book.author.name})

# 3. DRF APIView
class BookListAPIView(APIView):
    def get(self, request):
        books = Book.objects.all()
        return Response([{"title": b.title} for b in books])

# 4. DRF ViewSet
class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()

    def list(self, request):
        books = self.get_queryset()
        return Response([{"title": b.title, "author": b.author.name} for b in books])