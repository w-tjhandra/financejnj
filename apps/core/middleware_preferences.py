from django.utils import translation
from django.utils.cache import patch_vary_headers

from core.models import UserPreference

SUPPORTED_LANGUAGES = {"id", "en", "ko"}
LANGUAGE_SESSION_KEY = "_language"


class AccountPreferencesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = request.session.get(LANGUAGE_SESSION_KEY, "id")
        theme = "light"
        if language not in SUPPORTED_LANGUAGES:
            language = "id"
        if request.user.is_authenticated:
            preference = UserPreference.objects.filter(user=request.user).first()
            if preference is not None:
                language = preference.language
                theme = preference.theme
        request.ui_language = language
        request.ui_theme = theme
        translation.activate(language)
        response = self.get_response(request)
        response.headers.setdefault("Content-Language", language)
        if request.user.is_authenticated:
            patch_vary_headers(response, ("Cookie",))
        return response
