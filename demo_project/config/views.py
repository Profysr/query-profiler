from django.http import JsonResponse
from .models import Book


def NPlusOneBookListView(request):
    """Flawed endpoint: Accessing FK field without select_related in a loop."""
    books = Book.objects.all()
    data = [{"title": book.title, "author": book.author.name} for book in books]
    return JsonResponse({"books": data})