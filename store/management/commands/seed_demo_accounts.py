from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = (
        "Creates local/test-only demo accounts with KNOWN, PUBLICLY-"
        "DOCUMENTED passwords (admin/AdminPass123!, security_test_user/"
        "KnownGoodPass123). This is for local development and the "
        "security_testing/ scan script only. Deliberately NOT called by "
        "build.sh or anywhere in the deploy process — running this against "
        "a real, publicly reachable deployment would plant a known admin "
        "password on the internet. For your real production admin account, "
        "use `python manage.py createsuperuser` (interactively) or the "
        "DJANGO_SUPERUSER_* environment variables build.sh already supports."
    )

    def handle(self, *args, **options):
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "AdminPass123!")
            self.stdout.write(self.style.SUCCESS(
                "Created superuser 'admin' / 'AdminPass123!' — local/test use only, "
                "never deploy this account to a real site."
            ))

        # Dedicated account for automated security testing (kept separate
        # from 'admin' so brute-force/lockout tests don't interfere with
        # other checks run in the same scan).
        test_user, _ = User.objects.get_or_create(
            username="security_test_user", defaults={"email": "sectest@example.com"}
        )
        test_user.set_password("KnownGoodPass123")
        test_user.failed_login_attempts = 0
        test_user.locked_until = None
        test_user.save()

        self.stdout.write(self.style.SUCCESS("Demo accounts ready (admin, security_test_user)."))
