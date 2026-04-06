def user_roles(request):
    user = request.user
    is_system_admin = user.is_authenticated and user.is_superuser
    is_admin = user.is_authenticated and (not user.is_superuser) and user.groups.filter(name='Admin').exists()
    is_seller = user.is_authenticated and (not user.is_superuser) and (is_admin or user.groups.filter(name='Seller').exists())

    subscription_warning = None
    if user.is_authenticated and not user.is_superuser:
        profile = getattr(user, 'profile', None)
        client = profile.client if profile else None
        if client and client.is_expired and not client.is_paused:
            subscription_warning = f"Subscription expired on {client.subscription_end_date}. {client.grace_days_left} day(s) left before app pause."

    return {
        'is_system_admin': is_system_admin,
        'is_admin': is_admin,
        'is_seller': is_seller,
        'subscription_warning': subscription_warning,
    }