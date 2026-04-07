from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.forms import AuthenticationForm

from .models import ClientBusiness, Product, Transaction


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'barcode', 'buying_price', 'price', 'stock_quantity', 'low_stock_threshold']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}),
            'barcode': forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2', 'placeholder': 'Scan or type barcode'}),
            'buying_price': forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'step': '0.01'}),
            'price': forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'step': '0.01'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'min': 0}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'min': 1}),
        }


class SaleAddItemForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        widget=forms.Select(attrs={'class': 'w-full rounded border px-3 py-2'}),
    )
    quantity = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2'}))

    def __init__(self, *args, **kwargs):
        client = kwargs.pop('client', None)
        super().__init__(*args, **kwargs)
        queryset = Product.objects.filter(stock_quantity__gt=0)
        if client is not None:
            queryset = queryset.filter(client=client)
        self.fields['product'].queryset = queryset.order_by('name')


class SaleCheckoutForm(forms.Form):
    payment_method = forms.ChoiceField(
        choices=Transaction.PAYMENT_METHOD_CHOICES,
        initial=Transaction.PAYMENT_METHOD_CASH,
        widget=forms.HiddenInput(),
    )
    amount_paid = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, widget=forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'step': '0.01'}))
    change_not_given = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False, initial=0, widget=forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'step': '0.01'}))
    customer_name = forms.CharField(required=False, max_length=150, widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2', 'placeholder': 'Person collecting later'}))


class ChangeCollectionForm(forms.Form):
    amount_collected = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01, widget=forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2', 'step': '0.01'}))


class ClientBusinessForm(forms.ModelForm):
    admin_username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    admin_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    cashier_username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    cashier_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    subscription_start = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))
    subscription_months = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2'}))

    class Meta:
        model = ClientBusiness
        fields = ['business_name', 'subscription_start', 'subscription_months']
        widgets = {
            'business_name': forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        admin_username = cleaned_data.get('admin_username', '').strip()
        cashier_username = cleaned_data.get('cashier_username', '').strip()
        if admin_username and cashier_username and admin_username == cashier_username:
            raise forms.ValidationError('Admin and cashier usernames must be different.')
        return cleaned_data


class ClientBusinessUpdateForm(forms.ModelForm):
    subscription_start = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))
    subscription_months = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': 'w-full rounded border px-3 py-2'}))

    class Meta:
        model = ClientBusiness
        fields = ['business_name', 'subscription_start', 'subscription_months']
        widgets = {
            'business_name': forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}),
        }


class CashierCreateForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))


class ForcePasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    new_password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    new_password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))


class TransactionFilterForm(forms.Form):
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2', 'placeholder': 'Search by ID or product...'}))
    from_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))
    to_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))

    def clean(self):
        cleaned_data = super().clean()
        from_date = cleaned_data.get('from_date')
        to_date = cleaned_data.get('to_date')
        if from_date and to_date and from_date > to_date:
            raise forms.ValidationError('From date cannot be after To date.')
        return cleaned_data


class BackupExportForm(forms.Form):
    from_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))
    to_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))

    def clean(self):
        cleaned_data = super().clean()
        from_date = cleaned_data.get('from_date')
        to_date = cleaned_data.get('to_date')
        if from_date and to_date and from_date > to_date:
            raise forms.ValidationError('From date cannot be after To date.')
        return cleaned_data