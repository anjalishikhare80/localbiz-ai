from django.urls import path

from . import views

app_name = "ml"
urlpatterns = [
    path("", views.MLOverviewView.as_view(), name="overview"),
    path("train/", views.TrainView.as_view(), name="train"),
    path("anomalies/<int:pk>/reviewed/", views.MarkReviewedView.as_view(), name="reviewed"),
    path("recommend/<int:product_id>/", views.RecommendView.as_view(), name="recommend"),
]
