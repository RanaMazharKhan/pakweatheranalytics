from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q

class CaseInsensitiveAuthBackend(ModelBackend):
    """
    Custom authentication backend that allows logging in with either
    username or email, performing a case-insensitive lookup.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            return None
        
        try:
            # Case-insensitive lookup for username OR email
            user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
            if user is None:
                return None
        except Exception:
            return None
            
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
