from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ShareAccountViewSet, ShareTransactionViewSet

router = DefaultRouter()
router.register(r'accounts', ShareAccountViewSet, basename='share-accounts')
router.register(r'transactions', ShareTransactionViewSet, basename='share-transactions')

urlpatterns = [
    path('', include(router.urls)),
]