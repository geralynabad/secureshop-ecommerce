from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import User


class RegistrationTests(TestCase):
    def test_register_creates_user_with_hashed_password(self):
        response = self.client.post(reverse("accounts:register"), {
            "username": "newuser",
            "email": "newuser@example.com",
            "phone_number": "",
            "password1": "CorrectHorseBattery9",
            "password2": "CorrectHorseBattery9",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newuser")
        # Password must never be stored in plaintext.
        self.assertNotEqual(user.password, "CorrectHorseBattery9")
        self.assertTrue(user.password.startswith("pbkdf2_"))

    def test_weak_password_rejected(self):
        response = self.client.post(reverse("accounts:register"), {
            "username": "weakuser",
            "email": "weak@example.com",
            "password1": "12345678",
            "password2": "12345678",
        })
        self.assertEqual(response.status_code, 200)  # re-rendered with errors
        self.assertFalse(User.objects.filter(username="weakuser").exists())

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username="existing", email="dupe@example.com", password="Whatever12345")
        response = self.client.post(reverse("accounts:register"), {
            "username": "another",
            "email": "dupe@example.com",
            "password1": "CorrectHorseBattery9",
            "password2": "CorrectHorseBattery9",
        })
        self.assertContains(response, "already exists")


class LoginSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", email="bob@example.com", password="RightPassword123")

    def test_correct_login_succeeds(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "bob", "password": "RightPassword123",
        })
        self.assertEqual(response.status_code, 302)

    def test_wrong_password_shows_generic_error(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "bob", "password": "wrong",
        })
        # Must not reveal whether the username exists.
        self.assertContains(response, "Invalid username or password")
        self.assertNotContains(response, "password is incorrect")

    def test_account_locks_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "bob", "password": "wrong"})
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.locked_until)
        self.assertGreater(self.user.locked_until, timezone.now())

        # Even the correct password should be blocked while locked.
        response = self.client.post(reverse("accounts:login"), {
            "username": "bob", "password": "RightPassword123",
        })
        self.assertContains(response, "temporarily locked")

    def test_logout_requires_post(self):
        self.client.login(username="bob", password="RightPassword123")
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 405)  # GET not allowed


class ProfileEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ellie", email="ellie@example.com", password="EllieePass123")
        self.client.login(username="ellie", password="EllieePass123")

    def test_can_update_address_gender_birthday(self):
        response = self.client.post(reverse("accounts:edit_profile"), {
            "email": "ellie@example.com",
            "phone_number": "0917xxxxxxx",
            "address": "123 Rizal St, Tacloban City",
            "gender": "female",
            "birthday": "1998-05-12",
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.address, "123 Rizal St, Tacloban City")
        self.assertEqual(self.user.gender, "female")
        self.assertEqual(str(self.user.birthday), "1998-05-12")

    def test_avatar_upload_validates_real_image_content(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
        buf.seek(0)
        avatar = SimpleUploadedFile("me.jpg", buf.read(), content_type="image/jpeg")

        response = self.client.post(reverse("accounts:edit_profile"), {
            "email": "ellie@example.com", "phone_number": "", "address": "", "gender": "unspecified",
            "avatar": avatar,
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(bool(self.user.avatar))

    def test_fake_image_upload_rejected_on_profile(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        fake = SimpleUploadedFile("me.jpg", b"not a real image", content_type="image/jpeg")
        response = self.client.post(reverse("accounts:edit_profile"), {
            "email": "ellie@example.com", "phone_number": "", "address": "", "gender": "unspecified",
            "avatar": fake,
        })
        self.assertEqual(response.status_code, 200)  # re-rendered with error, not saved
        self.user.refresh_from_db()
        self.assertFalse(bool(self.user.avatar))


class SecurityHeaderTests(TestCase):
    def test_response_has_hardening_headers(self):
        response = self.client.get(reverse("store:product_list"))
        self.assertIn("Content-Security-Policy", response)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_csrf_protection_blocks_missing_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(reverse("accounts:login"), {
            "username": "bob", "password": "RightPassword123",
        })
        self.assertEqual(response.status_code, 403)
