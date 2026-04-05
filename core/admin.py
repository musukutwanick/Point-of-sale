from django.contrib import admin
from .models import Product, Transaction, TransactionItem


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ('name', 'price', 'stock_quantity', 'low_stock_threshold', 'updated_at')
	search_fields = ('name',)


class TransactionItemInline(admin.TabularInline):
	model = TransactionItem
	extra = 0
	readonly_fields = ('product', 'product_name', 'unit_price', 'quantity', 'line_total')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
	list_display = ('id', 'seller', 'total_amount', 'amount_paid', 'change_due', 'change_given', 'created_at')
	list_filter = ('created_at', 'seller')
	inlines = [TransactionItemInline]
