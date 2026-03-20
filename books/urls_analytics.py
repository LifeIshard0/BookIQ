from django.urls import path
from books.views_analytics import genre_trends, genre_quality, catalogue_summary

urlpatterns = [
    path('genre-trends/', genre_trends, name='analytics-genre-trends'),
    path('genre-quality/', genre_quality, name='analytics-genre-quality'),
    path('summary/', catalogue_summary, name='analytics-summary'),
]
