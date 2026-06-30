from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
import logging

from .forms import UserRegistrationForm, CustomLoginForm, UserProfileForm
from .models import UserProfile
from .tokens import account_activation_token

logger = logging.getLogger(__name__)


def register_view(request):
    if request.user.is_authenticated:
        return redirect('weather:dashboard')
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            
            # Check if email verification is required
            email_verification_required = getattr(settings, 'EMAIL_VERIFICATION_REQUIRED', True)
            if email_verification_required:
                user.is_active = False
            else:
                user.is_active = True
                
            user.save()
            UserProfile.objects.get_or_create(user=user)

            if email_verification_required:
                try:
                    send_verification_email(request, user)
                except Exception:
                    logger.exception('Failed to send verification email to %s', user.email)
                    messages.warning(
                        request,
                        'Your account was created, but we could not send the verification email. '
                        'Try signing in — we will resend the verification link automatically.',
                    )
                    return redirect('accounts:verification_sent')

                messages.success(request, 'Registration successful! Please check your email to verify your account.')
                return redirect('accounts:verification_sent')
            else:
                login(request, user, backend='accounts.backends.CaseInsensitiveAuthBackend')
                messages.success(request, 'Registration successful! Your account is active.')
                return redirect('weather:dashboard')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


def send_verification_email(request, user):
    if not user.email:
        raise ValueError('User has no email address on file.')

    subject = 'Verify your email - Weather Analytics Portal'
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = account_activation_token.make_token(user)
    verification_url = request.build_absolute_uri(
        reverse('accounts:verify_email', kwargs={'uidb64': uid, 'token': token})
    )

    # Store verification url in session for development debugging
    if settings.DEBUG:
        request.session['debug_verification_url'] = verification_url

    html_message = render_to_string('accounts/verification_email.html', {
        'user': user,
        'verification_url': verification_url,
    })

    send_mail(
        subject=subject,
        message=f'Please verify your email by visiting this link:\n\n{verification_url}',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
        html_message=html_message,
    )

# ADDED BACK: This is the function that actually activates the account when they click the link!
def verify_email_view(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    
    if user is not None and account_activation_token.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, 'Your email has been verified! You can now login.')
        return redirect('accounts:verification_success')
    else:
        messages.error(request, 'The verification link is invalid or has expired.')
        return redirect('accounts:verification_failed')


def verification_sent_view(request):
    context = {}
    if settings.DEBUG:
        context['debug_verification_url'] = request.session.get('debug_verification_url')
    return render(request, 'accounts/email_verification_sent.html', context)


def verification_success_view(request):
    return render(request, 'accounts/email_verification_success.html')


def verification_failed_view(request):
    return render(request, 'accounts/email_verification_failed.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('weather:dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Intercept inactive users with correct credentials to show email verification prompt
        try:
            from django.db.models import Q
            user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
            if user and user.check_password(password) and not user.is_active:
                messages.error(request, 'Please verify your email address before logging in.')
                try:
                    send_verification_email(request, user)
                except Exception:
                    logger.exception('Failed to resend verification email to %s', user.email)
                    messages.error(
                        request,
                        'We could not send a verification email. Please check your email settings or contact support.',
                    )
                return redirect('accounts:verification_sent')
        except Exception:
            pass

        form = CustomLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            next_url = request.GET.get('next', 'weather:dashboard')
            if next_url == 'weather:dashboard':
                return redirect('weather:dashboard')
            return redirect(next_url)
    else:
        form = CustomLoginForm()
    
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('weather:home')


@login_required
def profile_view(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=profile, user=request.user)
    
    return render(request, 'accounts/profile.html', {'form': form, 'profile': profile})