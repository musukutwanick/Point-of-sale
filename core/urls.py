from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import (
    UserLoginView,
    backup_database,
    changes_list,
    complete_sale,
    dashboard,
    home_redirect,
    new_sale,
    product_create,
    product_delete,
    product_list,
    product_update,
    remove_sale_item,
    transaction_list,
)

urlpatterns = [
    path('', home_redirect, name='home'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('dashboard/', dashboard, name='dashboard'),
    path('products/', product_list, name='product_list'),
    path('products/new/', product_create, name='product_create'),
    path('products/<int:pk>/edit/', product_update, name='product_update'),
    path('products/<int:pk>/delete/', product_delete, name='product_delete'),
    path('sales/new/', new_sale, name='new_sale'),
    path('sales/remove/<int:product_id>/', remove_sale_item, name='remove_sale_item'),
    path('sales/complete/', complete_sale, name='complete_sale'),
    path('changes/', changes_list, name='changes_list'),
    path('transactions/', transaction_list, name='transaction_list'),
    path('backup/', backup_database, name='backup_database'),
]