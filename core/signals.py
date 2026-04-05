from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.db.models.signals import post_migrate
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    if sender.name != 'core':
        return
    Group.objects.get_or_create(name='Admin')
    Group.objects.get_or_create(name='Seller')


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    else:
        UserProfile.objects.get_or_create(user=instance)