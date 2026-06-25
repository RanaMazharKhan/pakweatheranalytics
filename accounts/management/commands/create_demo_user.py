from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Create an active demo user for testing the dashboard'

    def handle(self, *args, **options):
        username = 'demo_user'
        email = 'demo_user@pakweather.com'
        password = 'DemoPassword123'
        
        user, created = User.objects.get_or_create(username=username, email=email)
        if created:
            user.set_password(password)
            user.is_active = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Successfully created active user: '{username}' with password: '{password}'"))
        else:
            user.set_password(password)
            user.is_active = True
            user.save()
            self.stdout.write(self.style.WARNING(f"User '{username}' already exists. Password updated and status set to active."))
