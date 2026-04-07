from decimal import Decimal
from datetime import datetime, timedelta
from io import BytesIO
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.db import models, transaction as db_transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate, TruncHour
from django.http import HttpResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .forms import (
	BackupExportForm,
	CashierCreateForm,
	ChangeCollectionForm,
	ClientBusinessForm,
	ClientBusinessUpdateForm,
	ForcePasswordChangeForm,
	LoginForm,
	ProductForm,
	SaleAddItemForm,
	SaleCheckoutForm,
	TransactionFilterForm,
)
from .models import ClientBusiness, Product, Transaction, TransactionItem, UserProfile

User = get_user_model()


def is_system_admin(user):
	return user.is_authenticated and user.is_superuser


def is_admin(user):
	return user.is_authenticated and (not user.is_superuser) and user.groups.filter(name='Admin').exists()


def is_seller(user):
	return user.is_authenticated and (not user.is_superuser) and (is_admin(user) or user.groups.filter(name='Seller').exists())


def _add_subscription_warning(request):
	profile = getattr(request.user, 'profile', None)
	client = profile.client if profile else None
	if not client:
		return

	if client.is_paused:
		messages.error(request, f'Subscription expired for {client.business_name}. App access is paused.')
		return

	if client.is_expired:
		messages.warning(
			request,
			f'Subscription expired on {client.subscription_end_date}. Grace period: {client.grace_days_left} day(s) left before app pause.',
		)


def _current_client(user):
	profile = getattr(user, 'profile', None)
	return profile.client if profile else None


class UserLoginView(LoginView):
	template_name = 'core/login.html'
	authentication_form = LoginForm
	redirect_authenticated_user = True

	def get_success_url(self):
		redirect_to = self.get_redirect_url()
		if redirect_to:
			return redirect_to

		if self.request.user.is_superuser:
			return reverse('sysadmin_dashboard')

		profile = getattr(self.request.user, 'profile', None)
		if profile and profile.client and not profile.client.is_active:
			return reverse('account_deactivated')

		if profile and profile.must_change_password:
			return reverse('force_change_password')

		if is_admin(self.request.user):
			return reverse('dashboard')
		if is_seller(self.request.user):
			return reverse('new_sale')
		return reverse('no_access')


@login_required
def home_redirect(request):
	if request.user.is_superuser:
		return redirect('sysadmin_dashboard')

	profile = getattr(request.user, 'profile', None)
	if profile and profile.client and not profile.client.is_active:
		return redirect('account_deactivated')

	if profile and profile.must_change_password:
		return redirect('force_change_password')

	if is_admin(request.user):
		return redirect('dashboard')
	if is_seller(request.user):
		return redirect('new_sale')
	return redirect('no_access')


@login_required
def no_access(request):
	return render(request, 'core/no_access.html', status=403)


@login_required
def account_deactivated(request):
	if request.user.is_superuser:
		return redirect('sysadmin_dashboard')
	return render(request, 'core/account_deactivated.html', status=403)


@login_required
@user_passes_test(is_system_admin, login_url='home')
def sysadmin_dashboard(request):
	clients = ClientBusiness.objects.annotate(
		cashier_count=Count('profiles', filter=Q(profiles__role=UserProfile.ROLE_CASHIER))
	).all().order_by('business_name')
	total_clients = clients.count()
	expired_clients = sum(1 for client in clients if client.is_expired and not client.is_paused)
	paused_clients = sum(1 for client in clients if client.is_paused)

	context = {
		'clients': clients,
		'total_clients': total_clients,
		'expired_clients': expired_clients,
		'paused_clients': paused_clients,
	}
	return render(request, 'core/sysadmin_dashboard.html', context)


@login_required
@user_passes_test(is_system_admin, login_url='home')
def client_add_cashier(request, pk):
	client = get_object_or_404(ClientBusiness, pk=pk)
	form = CashierCreateForm(request.POST or None)

	if request.method == 'POST' and form.is_valid():
		username = form.cleaned_data['username'].strip()
		password = form.cleaned_data['password']

		if User.objects.filter(username=username).exists():
			form.add_error('username', 'This username already exists.')
		else:
			seller_group, _ = Group.objects.get_or_create(name='Seller')
			cashier_user = User.objects.create_user(username=username, password=password)
			cashier_user.groups.add(seller_group)

			cashier_profile, _ = UserProfile.objects.get_or_create(user=cashier_user)
			cashier_profile.client = client
			cashier_profile.role = UserProfile.ROLE_CASHIER
			cashier_profile.must_change_password = True
			cashier_profile.save()

			messages.success(request, f'Cashier {username} added to {client.business_name}.')
			return redirect('sysadmin_dashboard')

	return render(request, 'core/cashier_form.html', {'form': form, 'client': client})


@login_required
@user_passes_test(is_system_admin, login_url='home')
def client_create(request):
	form = ClientBusinessForm(request.POST or None)
	if request.method == 'POST' and form.is_valid():
		admin_username = form.cleaned_data['admin_username'].strip()
		cashier_username = form.cleaned_data['cashier_username'].strip()

		if User.objects.filter(username=admin_username).exists():
			form.add_error('admin_username', 'This username already exists.')
		elif User.objects.filter(username=cashier_username).exists():
			form.add_error('cashier_username', 'This username already exists.')
		else:
			client = form.save()
			admin_group, _ = Group.objects.get_or_create(name='Admin')
			seller_group, _ = Group.objects.get_or_create(name='Seller')

			admin_user = User.objects.create_user(
				username=admin_username,
				password=form.cleaned_data['admin_password'],
			)
			admin_user.groups.add(admin_group)

			cashier_user = User.objects.create_user(
				username=cashier_username,
				password=form.cleaned_data['cashier_password'],
			)
			cashier_user.groups.add(seller_group)

			admin_profile, _ = UserProfile.objects.get_or_create(user=admin_user)
			admin_profile.client = client
			admin_profile.role = UserProfile.ROLE_ADMIN
			admin_profile.must_change_password = True
			admin_profile.save()

			cashier_profile, _ = UserProfile.objects.get_or_create(user=cashier_user)
			cashier_profile.client = client
			cashier_profile.role = UserProfile.ROLE_CASHIER
			cashier_profile.must_change_password = True
			cashier_profile.save()

			messages.success(request, 'Client business and user accounts created.')
			return redirect('sysadmin_dashboard')

	return render(request, 'core/client_form.html', {'form': form, 'title': 'Add Client Business'})


@login_required
@user_passes_test(is_system_admin, login_url='home')
def client_update(request, pk):
	client = get_object_or_404(ClientBusiness, pk=pk)
	form = ClientBusinessUpdateForm(request.POST or None, instance=client)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, 'Client business updated.')
		return redirect('sysadmin_dashboard')
	return render(request, 'core/client_form.html', {'form': form, 'title': 'Edit Client Business'})


@login_required
@user_passes_test(is_system_admin, login_url='home')
def client_delete(request, pk):
	client = get_object_or_404(ClientBusiness, pk=pk)
	if request.method == 'POST':
		users_to_delete = list(User.objects.filter(profile__client=client))
		for user in users_to_delete:
			user.delete()
		client.delete()
		messages.success(request, 'Client business deleted.')
		return redirect('sysadmin_dashboard')
	return render(request, 'core/client_confirm_delete.html', {'client': client})


@login_required
@user_passes_test(is_system_admin, login_url='home')
def client_toggle_active(request, pk):
	client = get_object_or_404(ClientBusiness, pk=pk)
	if request.method == 'POST':
		client.is_active = not client.is_active
		client.save(update_fields=['is_active'])
		if client.is_active:
			messages.success(request, f'{client.business_name} account activated.')
		else:
			messages.warning(request, f'{client.business_name} account deactivated.')
	return redirect('sysadmin_dashboard')


@login_required
def force_change_password(request):
	profile = getattr(request.user, 'profile', None)
	if request.user.is_superuser:
		return redirect('sysadmin_dashboard')
	if not profile or not profile.must_change_password:
		return redirect('home')

	form = ForcePasswordChangeForm(request.user, request.POST or None)
	if request.method == 'POST' and form.is_valid():
		user = form.save()
		profile.must_change_password = False
		profile.save(update_fields=['must_change_password'])
		update_session_auth_hash(request, user)
		messages.success(request, 'Password updated successfully.')
		return redirect('home')
	elif request.method == 'POST':
		messages.error(request, 'Password was not updated. Please fix the errors below.')

	return render(request, 'core/force_password_change.html', {'form': form})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def dashboard(request):
	_add_subscription_warning(request)
	client = _current_client(request.user)
	today = timezone.localdate()
	today_transactions = Transaction.objects.filter(created_at__date=today, client=client)
	total_sales = today_transactions.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
	today_profit = TransactionItem.objects.filter(transaction__created_at__date=today, transaction__client=client).aggregate(total=Sum('line_profit'))['total'] or Decimal('0')
	transaction_count = today_transactions.aggregate(count=Count('id'))['count'] or 0
	outstanding_change = today_transactions.aggregate(total=Sum(F('change_due') - F('change_given'), output_field=models.DecimalField()))['total'] or Decimal('0')
	low_stock_items = Product.objects.filter(client=client, stock_quantity__lte=F('low_stock_threshold')).order_by('stock_quantity')
	recent_transactions = Transaction.objects.filter(client=client).select_related('seller').order_by('-created_at')[:5]

	start_of_week = today - timedelta(days=today.weekday())
	weekly_sales = []
	for day_offset in range(7):
		day = start_of_week + timedelta(days=day_offset)
		total_for_day = Transaction.objects.filter(client=client, created_at__date=day).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
		weekly_sales.append({
			'label': day.strftime('%a'),
			'value': total_for_day,
		})

	max_week_sale = max((item['value'] for item in weekly_sales), default=Decimal('0'))
	if max_week_sale > 0:
		for item in weekly_sales:
			item['height_pct'] = int((item['value'] / max_week_sale) * 100)
	else:
		for item in weekly_sales:
			item['height_pct'] = 0

	context = {
		'total_sales': total_sales,
		'today_profit': today_profit,
		'transaction_count': transaction_count,
		'outstanding_change': outstanding_change,
		'low_stock_items': low_stock_items,
		'recent_transactions': recent_transactions,
		'weekly_sales': weekly_sales,
		'max_week_sale': max_week_sale,
		'today': today,
	}
	return render(request, 'core/dashboard.html', context)


@login_required
@user_passes_test(is_admin, login_url='no_access')
def reports_dashboard(request):
	client = _current_client(request.user)
	today = timezone.localdate()
	period = (request.GET.get('period') or 'daily').lower()
	from_date_str = (request.GET.get('from_date') or '').strip()
	to_date_str = (request.GET.get('to_date') or '').strip()
	if period not in {'daily', 'weekly', 'monthly'}:
		period = 'daily'

	start_date = None
	end_date = None
	if from_date_str or to_date_str:
		try:
			if from_date_str:
				start_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
			if to_date_str:
				end_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
		except ValueError:
			messages.error(request, 'Invalid date format. Use valid From/To dates.')
			start_date = None
			end_date = None

	if start_date and not end_date:
		end_date = start_date
	if end_date and not start_date:
		start_date = end_date

	if start_date and end_date and start_date > end_date:
		messages.error(request, 'From date cannot be after To date.')
		start_date = None
		end_date = None

	if not start_date or not end_date:
		if period == 'daily':
			start_date = today
			end_date = today
		elif period == 'weekly':
			start_date = today - timedelta(days=today.weekday())
			end_date = start_date + timedelta(days=6)
		else:
			start_date = today.replace(day=1)
			end_date = today.replace(day=monthrange(today.year, today.month)[1])

	transactions = Transaction.objects.filter(
		client=client,
		created_at__date__range=(start_date, end_date),
	)
	transaction_items = TransactionItem.objects.filter(transaction__in=transactions)

	total_sales = transactions.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
	total_transactions = transactions.count()
	total_profit = transaction_items.aggregate(total=Sum('line_profit'))['total'] or Decimal('0')

	best_item_data = transaction_items.values('product_name').annotate(total_qty=Sum('quantity')).order_by('-total_qty').first()
	best_selling_item = best_item_data['product_name'] if best_item_data else 'N/A'

	if period == 'daily':
		sales_points = transactions.annotate(bucket=TruncHour('created_at')).values('bucket').annotate(total=Sum('total_amount')).order_by('bucket')
		sales_by_bucket = {item['bucket'].hour: float(item['total']) for item in sales_points if item['bucket']}
		sales_labels = [f'{hour:02d}:00' for hour in range(24)]
		sales_values = [sales_by_bucket.get(hour, 0) for hour in range(24)]
	else:
		sales_points = transactions.annotate(bucket=TruncDate('created_at')).values('bucket').annotate(total=Sum('total_amount')).order_by('bucket')
		sales_by_bucket = {item['bucket']: float(item['total']) for item in sales_points if item['bucket']}
		total_days = (end_date - start_date).days + 1
		sales_labels = []
		sales_values = []
		for day_index in range(total_days):
			day = start_date + timedelta(days=day_index)
			sales_labels.append(day.strftime('%b %d'))
			sales_values.append(sales_by_bucket.get(day, 0))

	product_qty_stats = list(
		transaction_items.values('product_name')
		.annotate(total_qty=Sum('quantity'))
		.order_by('-total_qty')
	)
	top_products = product_qty_stats[:8]
	lowest_products = list(reversed(product_qty_stats[-8:])) if product_qty_stats else []

	context = {
		'period': period,
		'start_date': start_date,
		'end_date': end_date,
		'from_date_value': start_date.strftime('%Y-%m-%d'),
		'to_date_value': end_date.strftime('%Y-%m-%d'),
		'total_sales': total_sales,
		'total_transactions': total_transactions,
		'total_profit': total_profit,
		'best_selling_item': best_selling_item,
		'sales_labels': sales_labels,
		'sales_values': sales_values,
		'top_product_labels': [item['product_name'] for item in top_products],
		'top_product_values': [item['total_qty'] for item in top_products],
		'low_product_labels': [item['product_name'] for item in lowest_products],
		'low_product_values': [item['total_qty'] for item in lowest_products],
	}
	return render(request, 'core/reports_dashboard.html', context)


@login_required
@user_passes_test(is_admin, login_url='no_access')
def product_list(request):
	products = Product.objects.filter(client=_current_client(request.user))
	return render(request, 'core/product_list.html', {'products': products})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def product_create(request):
	client = _current_client(request.user)
	form = ProductForm(request.POST or None)
	if request.method == 'POST' and form.is_valid():
		product = form.save(commit=False)
		product.client = client
		product.save()
		messages.success(request, 'Product created.')
		return redirect('product_list')
	return render(request, 'core/product_form.html', {'form': form, 'title': 'Add Product'})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def product_update(request, pk):
	product = get_object_or_404(Product, pk=pk, client=_current_client(request.user))
	form = ProductForm(request.POST or None, instance=product)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, 'Product updated.')
		return redirect('product_list')
	return render(request, 'core/product_form.html', {'form': form, 'title': 'Edit Product'})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def product_delete(request, pk):
	product = get_object_or_404(Product, pk=pk, client=_current_client(request.user))
	if request.method == 'POST':
		product.delete()
		messages.success(request, 'Product deleted.')
		return redirect('product_list')
	return render(request, 'core/product_confirm_delete.html', {'product': product})


def _get_cart(request):
	return request.session.setdefault('cart', {})


def _build_cart_items(cart, client=None):
	products = Product.objects.filter(id__in=cart.keys())
	if client is not None:
		products = products.filter(client=client)
	product_map = {str(product.id): product for product in products}
	items = []
	total = Decimal('0')
	for product_id, quantity in cart.items():
		product = product_map.get(str(product_id))
		if not product:
			continue
		line_total = product.price * quantity
		total += line_total
		items.append({'product': product, 'quantity': quantity, 'line_total': line_total})
	return items, total


@login_required
@user_passes_test(is_seller, login_url='no_access')
def new_sale(request):
	_add_subscription_warning(request)
	client = _current_client(request.user)
	cart = _get_cart(request)
	query = request.GET.get('q', '').strip()

	add_form = SaleAddItemForm(request.POST or None, client=client)
	if request.method == 'POST' and request.POST.get('action') == 'add_item' and add_form.is_valid():
		product = add_form.cleaned_data['product']
		quantity = add_form.cleaned_data['quantity']
		existing = cart.get(str(product.id), 0)
		if existing + quantity > product.stock_quantity:
			messages.error(request, f'Only {product.stock_quantity} units available for {product.name}.')
		else:
			cart[str(product.id)] = existing + quantity
			request.session.modified = True
			messages.success(request, f'Added {product.name} x {quantity}.')
			return redirect('new_sale')

	if query:
		products = Product.objects.filter(Q(client=client) & Q(name__icontains=query) & Q(stock_quantity__gt=0)).order_by('name')
	else:
		products = Product.objects.filter(client=client, stock_quantity__gt=0).order_by('name')[:20]

	change_customers = Transaction.objects.filter(client=client).exclude(customer_name='').values('customer_name').annotate(
		available_change=Sum(
			F('change_due') - F('change_given'),
			output_field=models.DecimalField(max_digits=10, decimal_places=2),
		)
	).filter(available_change__gt=0).order_by('customer_name')

	cart_items, cart_total = _build_cart_items(cart, client=client)
	checkout_form = SaleCheckoutForm()

	context = {
		'products': products,
		'query': query,
		'add_form': add_form,
		'checkout_form': checkout_form,
		'cart_items': cart_items,
		'cart_total': cart_total,
		'change_customers': change_customers,
	}
	return render(request, 'core/sale.html', context)


@login_required
@user_passes_test(is_seller, login_url='no_access')
def remove_sale_item(request, product_id):
	if request.method == 'POST':
		cart = _get_cart(request)
		cart.pop(str(product_id), None)
		request.session.modified = True
	return redirect('new_sale')


@login_required
@user_passes_test(is_seller, login_url='no_access')
def complete_sale(request):
	if request.method != 'POST':
		return redirect('new_sale')

	cart = _get_cart(request)
	if not cart:
		messages.error(request, 'Cart is empty.')
		return redirect('new_sale')

	checkout_form = SaleCheckoutForm(request.POST)
	if not checkout_form.is_valid():
		messages.error(request, 'Invalid payment details.')
		return redirect('new_sale')

	client = _current_client(request.user)
	cart_items, cart_total = _build_cart_items(cart, client=client)
	use_change_customer = (request.POST.get('use_change_customer') or '').strip()
	is_using_change = bool(use_change_customer)

	payment_method = checkout_form.cleaned_data['payment_method']
	amount_paid = checkout_form.cleaned_data['amount_paid']
	change_not_given = checkout_form.cleaned_data['change_not_given']
	if change_not_given is None:
		change_not_given = Decimal('0')
	customer_name = checkout_form.cleaned_data['customer_name'].strip()

	if is_using_change:
		amount_paid = cart_total
		change_due = Decimal('0')
		change_not_given = Decimal('0')
		if not customer_name:
			customer_name = use_change_customer
	else:
		change_due = amount_paid - cart_total if amount_paid > cart_total else Decimal('0')

	change_given = change_due - change_not_given

	if change_not_given > change_due:
		messages.error(request, 'Change not given cannot exceed change due.')
		return redirect('new_sale')

	if change_given < 0:
		messages.error(request, 'Invalid change values.')
		return redirect('new_sale')

	if change_not_given > 0 and not customer_name:
		messages.error(request, 'Enter customer name when change is not given.')
		return redirect('new_sale')

	try:
		with db_transaction.atomic():
			if is_using_change:
				credit_transactions = Transaction.objects.select_for_update().filter(
					client=client,
					customer_name__iexact=use_change_customer,
					change_due__gt=F('change_given'),
				).order_by('created_at', 'id')

				available_change = credit_transactions.aggregate(
					total=Sum(
						F('change_due') - F('change_given'),
						output_field=models.DecimalField(max_digits=10, decimal_places=2),
					)
				)['total'] or Decimal('0')

				if available_change < cart_total:
					raise ValueError(
						f'{use_change_customer} only has $ {available_change} change available. '
						f'Sale total is $ {cart_total}.'
					)

			transaction_record = Transaction.objects.create(
				seller=request.user,
				client=client,
				payment_method=payment_method,
				customer_name=customer_name,
				total_amount=cart_total,
				amount_paid=amount_paid,
				change_due=change_due,
				change_given=change_given,
			)

			for item in cart_items:
				product = Product.objects.select_for_update().get(pk=item['product'].pk)
				if item['quantity'] > product.stock_quantity:
					raise ValueError(f'Insufficient stock for {product.name}.')

				product.stock_quantity -= item['quantity']
				product.save(update_fields=['stock_quantity', 'updated_at'])

				TransactionItem.objects.create(
					transaction=transaction_record,
					product=product,
					product_name=product.name,
					unit_buying_price=product.buying_price,
					unit_price=item['product'].price,
					quantity=item['quantity'],
					line_total=item['line_total'],
					line_profit=(product.price - product.buying_price) * item['quantity'],
				)

			if is_using_change:
				remaining_to_apply = cart_total
				for credit_tx in credit_transactions:
					if remaining_to_apply <= 0:
						break
					credit_available = credit_tx.change_due - credit_tx.change_given
					if credit_available <= 0:
						continue

					applied_amount = min(credit_available, remaining_to_apply)
					credit_tx.change_given = credit_tx.change_given + applied_amount
					credit_tx.save(update_fields=['change_given'])
					remaining_to_apply -= applied_amount

		request.session['cart'] = {}
		request.session.modified = True
		if is_using_change:
			messages.success(request, f'Sale completed using {use_change_customer}\'s saved change. Transaction #{transaction_record.id}.')
		else:
			messages.success(request, f'Sale completed. Transaction #{transaction_record.id}.')
		return redirect('receipt_detail', tx_id=transaction_record.id)
	except ValueError as exc:
		messages.error(request, str(exc))

	return redirect('new_sale')


@login_required
@user_passes_test(is_seller, login_url='no_access')
def receipt_detail(request, tx_id):
	tx = get_object_or_404(
		Transaction.objects.select_related('seller', 'client').prefetch_related('items'),
		pk=tx_id,
		client=_current_client(request.user),
	)
	return render(request, 'core/receipt.html', {'tx': tx})


@login_required
@user_passes_test(is_seller, login_url='no_access')
def receipt_pdf(request, tx_id):
	tx = get_object_or_404(
		Transaction.objects.select_related('seller', 'client').prefetch_related('items'),
		pk=tx_id,
		client=_current_client(request.user),
	)

	buffer = BytesIO()
	pdf = canvas.Canvas(buffer, pagesize=A4)
	page_width, page_height = A4

	y = page_height - 50
	pdf.setFont('Helvetica-Bold', 14)
	pdf.drawString(40, y, tx.client.business_name if tx.client else 'Point of Sale')
	y -= 22
	pdf.setFont('Helvetica', 10)
	pdf.drawString(40, y, f'Receipt #{tx.id}')
	y -= 16
	pdf.drawString(40, y, f'Date: {tx.created_at.strftime("%Y-%m-%d %H:%M")}' )
	y -= 16
	pdf.drawString(40, y, f'Cashier: {tx.seller.username}')
	y -= 24

	pdf.setFont('Helvetica-Bold', 10)
	pdf.drawString(40, y, 'Item')
	pdf.drawString(290, y, 'Qty')
	pdf.drawString(340, y, 'Unit')
	pdf.drawString(430, y, 'Line Total')
	y -= 14
	pdf.line(40, y, page_width - 40, y)
	y -= 14

	pdf.setFont('Helvetica', 10)
	for item in tx.items.all():
		if y < 90:
			pdf.showPage()
			y = page_height - 50
			pdf.setFont('Helvetica', 10)
		pdf.drawString(40, y, item.product_name[:40])
		pdf.drawRightString(320, y, str(item.quantity))
		pdf.drawRightString(400, y, f'${item.unit_price:.2f}')
		pdf.drawRightString(page_width - 40, y, f'${item.line_total:.2f}')
		y -= 16

	y -= 8
	pdf.line(40, y, page_width - 40, y)
	y -= 20
	pdf.setFont('Helvetica-Bold', 11)
	pdf.drawRightString(page_width - 40, y, f'Total: ${tx.total_amount:.2f}')
	y -= 16
	pdf.setFont('Helvetica', 10)
	pdf.drawRightString(page_width - 40, y, f'Paid: ${tx.amount_paid:.2f}')
	y -= 16
	pdf.drawRightString(page_width - 40, y, f'Change: ${tx.change_due:.2f}')

	pdf.showPage()
	pdf.save()
	buffer.seek(0)

	response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
	response['Content-Disposition'] = f'attachment; filename="receipt_{tx.id}.pdf"'
	return response


@login_required
@user_passes_test(is_seller, login_url='no_access')
def changes_list(request):
	if request.method == 'POST':
		transaction_id = request.POST.get('transaction_id')
		tx = get_object_or_404(Transaction, pk=transaction_id)
		form = ChangeCollectionForm(request.POST)
		if form.is_valid():
			amount_collected = form.cleaned_data['amount_collected']
			remaining = tx.change_not_given
			if amount_collected > remaining:
				messages.error(request, 'Amount collected cannot exceed remaining change.')
			else:
				tx.change_given = tx.change_given + amount_collected
				tx.save(update_fields=['change_given'])
				messages.success(request, f'Updated change for Transaction #{tx.id}.')
		return redirect('changes_list')

	transactions = Transaction.objects.select_related('seller').filter(client=_current_client(request.user), change_due__gt=F('change_given')).order_by('-created_at')
	return render(request, 'core/changes.html', {'transactions': transactions})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def transaction_list(request):
	form = TransactionFilterForm(request.GET or None)
	transactions = Transaction.objects.prefetch_related('items').select_related('seller').filter(client=_current_client(request.user))
	if form.is_valid():
		q = (form.cleaned_data.get('q') or '').strip()
		from_date = form.cleaned_data.get('from_date')
		to_date = form.cleaned_data.get('to_date')

		if q:
			id_query = None
			if q.lower().startswith('txn-'):
				possible_id = q.split('-', 1)[-1]
				if possible_id.isdigit():
					id_query = int(possible_id)
			elif q.isdigit():
				id_query = int(q)

			search_filter = Q(items__product_name__icontains=q)
			if id_query is not None:
				search_filter = search_filter | Q(id=id_query)
			transactions = transactions.filter(search_filter).distinct()

		if from_date:
			transactions = transactions.filter(created_at__date__gte=from_date)
		if to_date:
			transactions = transactions.filter(created_at__date__lte=to_date)

	transactions = transactions.order_by('-created_at')
	
	total_amount_filtered = transactions.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
	total_profit_filtered = TransactionItem.objects.filter(transaction__in=transactions).aggregate(total=Sum('line_profit'))['total'] or Decimal('0')
	outstanding_change_filtered = transactions.aggregate(total=Sum(F('change_due') - F('change_given'), output_field=models.DecimalField()))['total'] or Decimal('0')
	transaction_count_filtered = transactions.count()
	
	return render(request, 'core/transactions.html', {
		'transactions': transactions,
		'form': form,
		'total_amount_filtered': total_amount_filtered,
		'total_profit_filtered': total_profit_filtered,
		'outstanding_change_filtered': outstanding_change_filtered,
		'transaction_count_filtered': transaction_count_filtered,
	})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def backup_database(request):
	client = _current_client(request.user)
	if request.method == 'POST':
		form = BackupExportForm(request.POST)
		if form.is_valid():
			from_date = form.cleaned_data['from_date']
			to_date = form.cleaned_data['to_date']

			workbook = Workbook()
			stock_sheet = workbook.active
			stock_sheet.title = 'Stock Levels'
			stock_sheet.append([
				'Product',
				'Buying Price',
				'Selling Price',
				'Profit Per Unit',
				'Stock Quantity',
			])

			products = Product.objects.filter(client=client).order_by('name')
			for product in products:
				stock_sheet.append([
					product.name,
					float(product.buying_price),
					float(product.price),
					float(product.unit_profit),
					product.stock_quantity,
				])

			transactions_sheet = workbook.create_sheet(title='Transactions')
			transactions_sheet.append([
				'Transaction ID',
				'Date Time',
				'Seller',
				'Payment Method',
				'Customer Name',
				'Product',
				'Quantity',
				'Buying Price',
				'Selling Price',
				'Line Total',
				'Line Profit',
				'Transaction Total',
				'Amount Paid',
				'Change Due',
				'Change Given',
			])

			items = TransactionItem.objects.select_related('transaction', 'transaction__seller').filter(
				transaction__client=client,
				transaction__created_at__date__range=(from_date, to_date),
			).order_by('transaction__created_at', 'transaction_id', 'id')

			for item in items:
				tx = item.transaction
				transactions_sheet.append([
					tx.id,
					tx.created_at.strftime('%Y-%m-%d %H:%M:%S'),
					tx.seller.username,
					tx.get_payment_method_display(),
					tx.customer_name,
					item.product_name,
					item.quantity,
					float(item.unit_buying_price),
					float(item.unit_price),
					float(item.line_total),
					float(item.line_profit),
					float(tx.total_amount),
					float(tx.amount_paid),
					float(tx.change_due),
					float(tx.change_given),
				])

			filename = f"backup_{from_date.strftime('%Y%m%d')}_to_{to_date.strftime('%Y%m%d')}.xlsx"
			response = HttpResponse(
				content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
			)
			response['Content-Disposition'] = f'attachment; filename="{filename}"'
			workbook.save(response)
			return response
	else:
		today = timezone.localdate()
		form = BackupExportForm(initial={'from_date': today, 'to_date': today})

	return render(request, 'core/backup.html', {'form': form})
