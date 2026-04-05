from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Product, Transaction


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full rounded border px-3 py-2'}))


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'price', 'stock_quantity', 'low_stock_threshold']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded border px-3 py-2'}),
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
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(stock_quantity__gt=0).order_by('name')


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


class TransactionFilterForm(forms.Form):
    date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full rounded border px-3 py-2'}))