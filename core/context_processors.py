def user_roles(request):
    user = request.user
    is_admin = user.is_authenticated and (user.is_superuser or user.groups.filter(name='Admin').exists())
    is_seller = user.is_authenticated and (is_admin or user.groups.filter(name='Seller').exists())
    return {
        'is_admin': is_admin,
        'is_seller': is_seller,
    }