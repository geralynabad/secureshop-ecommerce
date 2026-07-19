import logging
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils import timezone
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
from django.views.decorators.http import require_POST

from .forms import RegisterForm, LoginForm, ProfileEditForm
from .models import User

logger = logging.getLogger("accounts")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            logger.info("New account registered: %s", user.username)
            login(request, user)
            messages.success(request, "Welcome! Your account has been created.")
            return redirect("store:product_list")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


# django-ratelimit throttles by IP as a first line of defense against
# credential-stuffing / brute force (A07:2021). The per-account lockout
# below is a second, independent layer.
@ratelimit(key="ip", rate="10/m", block=True)
def user_login(request):
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        username = request.POST.get("username", "")

        try:
            candidate = User.objects.get(username=username)
        except User.DoesNotExist:
            candidate = None

        if candidate and candidate.locked_until and candidate.locked_until > timezone.now():
            messages.error(request, "This account is temporarily locked. Try again later.")
            logger.warning("Login blocked (locked account): %s", username)
            return render(request, "registration/login.html", {"form": form})

        if form.is_valid():
            user = form.get_user()
            user.failed_login_attempts = 0
            user.locked_until = None
            user.save(update_fields=["failed_login_attempts", "locked_until"])
            login(request, user)
            logger.info("Successful login: %s", username)
            next_url = request.GET.get("next") or "store:product_list"
            return redirect(next_url)
        else:
            if candidate:
                candidate.failed_login_attempts += 1
                if candidate.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                    candidate.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
                    logger.warning("Account locked after repeated failures: %s", username)
                candidate.save(update_fields=["failed_login_attempts", "locked_until"])
            logger.warning("Failed login attempt: %s", username)
            # Deliberately generic message — do not reveal whether the
            # username exists (prevents user enumeration).
            messages.error(request, "Invalid username or password.")
    else:
        form = LoginForm()
    return render(request, "registration/login.html", {"form": form})


@login_required
@require_POST
def user_logout(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("store:product_list")


@login_required
def profile(request):
    return render(request, "registration/profile.html")


@login_required
def edit_profile(request):
    if request.method == "POST":
        # request.FILES is required here for the avatar upload to work —
        # without it, Django silently ignores the file input entirely.
        form = ProfileEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            logger.info("Profile updated: %s", request.user.username)
            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileEditForm(instance=request.user)
    return render(request, "registration/edit_profile.html", {"form": form})
