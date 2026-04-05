from decimal import Decimal
from pathlib import Path
import shutil
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.db import models, transaction as db_transaction
from django.db.models import Count, F, Q, Sum
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
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
	return user.is_authenticated and (user.is_superuser or user.groups.filter(name='Admin').exists())


def is_seller(user):
	return user.is_authenticated and (is_admin(user) or user.groups.filter(name='Seller').exists())


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
@user_passes_test(is_system_admin, login_url='home')
def sysadmin_dashboard(request):
	clients = ClientBusiness.objects.all().order_by('business_name')
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
	transaction_count = today_transactions.aggregate(count=Count('id'))['count'] or 0
	outstanding_change = today_transactions.aggregate(total=Sum(F('change_due') - F('change_given'), output_field=models.DecimalField()))['total'] or Decimal('0')
	low_stock_items = Product.objects.filter(client=client, stock_quantity__lte=F('low_stock_threshold')).order_by('stock_quantity')

	context = {
		'total_sales': total_sales,
		'transaction_count': transaction_count,
		'outstanding_change': outstanding_change,
		'low_stock_items': low_stock_items,
		'today': today,
	}
	return render(request, 'core/dashboard.html', context)


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

	cart_items, cart_total = _build_cart_items(cart, client=client)
	checkout_form = SaleCheckoutForm()

	context = {
		'products': products,
		'query': query,
		'add_form': add_form,
		'checkout_form': checkout_form,
		'cart_items': cart_items,
		'cart_total': cart_total,
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
	payment_method = checkout_form.cleaned_data['payment_method']
	amount_paid = checkout_form.cleaned_data['amount_paid']
	change_due = amount_paid - cart_total if amount_paid > cart_total else Decimal('0')
	change_not_given = checkout_form.cleaned_data['change_not_given']
	if change_not_given is None:
		change_not_given = Decimal('0')
	customer_name = checkout_form.cleaned_data['customer_name'].strip()
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
					unit_price=item['product'].price,
					quantity=item['quantity'],
					line_total=item['line_total'],
				)

		request.session['cart'] = {}
		request.session.modified = True
		messages.success(request, f'Sale completed. Transaction #{transaction_record.id}.')
	except ValueError as exc:
		messages.error(request, str(exc))

	return redirect('new_sale')


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
	filtered_date = None
	if form.is_valid() and form.cleaned_data.get('date'):
		filtered_date = form.cleaned_data['date']
		transactions = transactions.filter(created_at__date=filtered_date)
	transactions = transactions.order_by('-created_at')
	
	total_amount_filtered = transactions.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
	outstanding_change_filtered = transactions.aggregate(total=Sum(F('change_due') - F('change_given'), output_field=models.DecimalField()))['total'] or Decimal('0')
	
	return render(request, 'core/transactions.html', {
		'transactions': transactions,
		'form': form,
		'filtered_date': filtered_date,
		'total_amount_filtered': total_amount_filtered,
		'outstanding_change_filtered': outstanding_change_filtered,
	})


@login_required
@user_passes_test(is_admin, login_url='no_access')
def backup_database(request):
	if request.method == 'POST':
		db_path = Path(settings.BASE_DIR) / 'db.sqlite3'
		backup_dir = Path(settings.BASE_DIR) / 'backups'
		backup_dir.mkdir(exist_ok=True)
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		backup_file = backup_dir / f'backup_{timestamp}.sqlite3'
		shutil.copy2(db_path, backup_file)
		messages.success(request, f'Backup created: {backup_file.name}')
		return redirect('backup_database')
	return render(request, 'core/backup.html')
