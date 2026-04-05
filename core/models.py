from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Product(models.Model):
	client = models.ForeignKey('ClientBusiness', on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
	name = models.CharField(max_length=150)
	price = models.DecimalField(max_digits=10, decimal_places=2)
	stock_quantity = models.PositiveIntegerField(default=0)
	low_stock_threshold = models.PositiveIntegerField(default=5)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']
		constraints = [
			models.UniqueConstraint(fields=['client', 'name'], name='unique_product_name_per_client'),
		]

	def __str__(self):
		return f"{self.name} ({self.stock_quantity})"

	@property
	def is_low_stock(self):
		return self.stock_quantity <= self.low_stock_threshold


class ClientBusiness(models.Model):
	business_name = models.CharField(max_length=200, unique=True)
	subscription_start = models.DateField(default=timezone.localdate)
	subscription_months = models.PositiveIntegerField(default=1)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['business_name']

	def __str__(self):
		return self.business_name

	@property
	def subscription_end_date(self):
		return self.subscription_start + timedelta(days=30 * self.subscription_months)

	@property
	def grace_end_date(self):
		return self.subscription_end_date + timedelta(days=3)

	@property
	def is_expired(self):
		return timezone.localdate() > self.subscription_end_date

	@property
	def is_paused(self):
		return timezone.localdate() > self.grace_end_date

	@property
	def grace_days_left(self):
		remaining = (self.grace_end_date - timezone.localdate()).days
		return remaining if remaining > 0 else 0


class UserProfile(models.Model):
	ROLE_ADMIN = 'admin'
	ROLE_CASHIER = 'cashier'
	ROLE_CHOICES = [
		(ROLE_ADMIN, 'Admin'),
		(ROLE_CASHIER, 'Cashier'),
	]

	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
	client = models.ForeignKey(ClientBusiness, on_delete=models.SET_NULL, null=True, blank=True, related_name='profiles')
	role = models.CharField(max_length=20, choices=ROLE_CHOICES, blank=True)
	must_change_password = models.BooleanField(default=False)

	def __str__(self):
		return f"{self.user.username} profile"


class Transaction(models.Model):
	PAYMENT_METHOD_CASH = 'cash'
	PAYMENT_METHOD_ECOCASH = 'ecocash'
	PAYMENT_METHOD_CHOICES = [
		(PAYMENT_METHOD_CASH, 'Cash'),
		(PAYMENT_METHOD_ECOCASH, 'EcoCash'),
	]

	seller = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sales')
	client = models.ForeignKey('ClientBusiness', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
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

