from django.shortcuts import redirect, render


class ClientAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if not user.is_authenticated or user.is_superuser:
            return self.get_response(request)

        path = request.path.rstrip('/') or '/'

        allowed_paths = {
            '/login',
            '/logout',
            '/force-change-password',
            '/no-access',
            '/account-deactivated',
        }

        if path in allowed_paths or path.startswith('/admin'):
            return self.get_response(request)

        profile = getattr(user, 'profile', None)
        if not profile:
            return self.get_response(request)

        if profile.must_change_password:
            return redirect('force_change_password')

        client = profile.client
        if client and not client.is_active:
            return redirect('account_deactivated')

        if client and client.is_paused:
            return render(request, 'core/subscription_paused.html', {'client': client}, status=403)

        return self.get_response(request)
