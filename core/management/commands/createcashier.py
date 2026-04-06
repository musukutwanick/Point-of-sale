from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from django.utils import timezone
from core.models import ClientBusiness, UserProfile


class Command(BaseCommand):
    help = 'Create default cashier user with client business'

    def handle(self, *args, **kwargs):
        # Create default client business if it doesn't exist
        client, client_created = ClientBusiness.objects.get_or_create(
            business_name='Default Business',
            defaults={
                'subscription_start': timezone.localdate(),
                'subscription_months': 12,
                'is_active': True,
            }
        )
        if client_created:
            self.stdout.write(self.style.SUCCESS(f'Client business created: {client.business_name}'))
        else:
            self.stdout.write(f'Client business already exists: {client.business_name}')

        # Create cashier user if it doesn't exist
        if not User.objects.filter(username='cashier').exists():
            cashier_user = User.objects.create_user(username='cashier', password='cashier123')
            self.stdout.write(self.style.SUCCESS('Cashier user created: username=cashier, password=cashier123'))
            
            # Add to Seller group
            seller_group, _ = Group.objects.get_or_create(name='Seller')
            cashier_user.groups.add(seller_group)
            
            # Create user profile
            profile, _ = UserProfile.objects.get_or_create(user=cashier_user)
            profile.client = client
            profile.role = UserProfile.ROLE_CASHIER
            profile.must_change_password = True
            profile.save()
            self.stdout.write(self.style.SUCCESS(f'Profile created for cashier, assigned to {client.business_name}'))
        else:
            self.stdout.write('Cashier user already exists')
