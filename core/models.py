from django.db import models
from django.contrib.auth.models import User


class Product(models.Model):
	name = models.CharField(max_length=150, unique=True)
	price = models.DecimalField(max_digits=10, decimal_places=2)
	stock_quantity = models.PositiveIntegerField(default=0)
	low_stock_threshold = models.PositiveIntegerField(default=5)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return f"{self.name} ({self.stock_quantity})"

	@property
	def is_low_stock(self):
		return self.stock_quantity <= self.low_stock_threshold


class Transaction(models.Model):
	PAYMENT_METHOD_CASH = 'cash'
	PAYMENT_METHOD_ECOCASH = 'ecocash'
	PAYMENT_METHOD_CHOICES = [
		(PAYMENT_METHOD_CASH, 'Cash'),
		(PAYMENT_METHOD_ECOCASH, 'EcoCash'),
	]

	seller = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sales')
	payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default=PAYMENT_METHOD_CASH)
	customer_name = models.CharField(max_length=150, blank=True)
	total_amount = models.DecimalField(max_digits=10, decimal_places=2)
	amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
	change_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	change_given = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f"Transaction #{self.id}"

	@property
	def change_not_given(self):
		not_given = self.change_due - self.change_given
		return not_given if not_given > 0 else 0

	@property
	def has_outstanding_change(self):
		return self.change_not_given > 0


class TransactionItem(models.Model):
	transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
	product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
	product_name = models.CharField(max_length=150)
	unit_price = models.DecimalField(max_digits=10, decimal_places=2)
	quantity = models.PositiveIntegerField()
	line_total = models.DecimalField(max_digits=10, decimal_places=2)

	def __str__(self):
		return f"{self.product_name} x {self.quantity}"

