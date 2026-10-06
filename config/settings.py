import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('WORKBENCH_DATA_DIR', BASE_DIR / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.environ.get('WORKBENCH_SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('Set WORKBENCH_SECRET_KEY before starting the application.')

DEBUG = os.environ.get('WORKBENCH_DEBUG') == '1'
ALLOWED_HOSTS = [x.strip() for x in os.environ.get('WORKBENCH_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.environ.get('WORKBENCH_CSRF_ORIGINS', '').split(',') if x.strip()]

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'core', 'aihub.apps.AihubConfig',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.LoginRoleMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'core.context_processors.role',
        'core.context_processors.shell',
        'core.context_processors.email_mode',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_DIR / 'workbench.sqlite3', 'OPTIONS': {'timeout': 20}}}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
if DEBUG or 'test' in sys.argv:
    # 本地开发和自动化测试都不运行 collectstatic：直接按原始文件名提供静态文件。
    STORAGES['staticfiles'] = {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
MEDIA_ROOT = DATA_DIR / 'private_uploads'
MEDIA_URL = '/not-public/'  # No URL route serves this location.
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'workspace_home'
LOGOUT_REDIRECT_URL = 'public_home'

# 邮件：用于成员自助找回密码。只有「开发模式 且 没配 SMTP」时才用控制台后端，
# 重置链接与验证码会直接打印在 runserver 输出里；配了 SMTP 就真实发信（本地也一样）。
# 生产必须配置 SMTP（见 .env.example 与运维说明），否则成员点「忘记密码」会失败。
EMAIL_HOST = os.environ.get('WORKBENCH_EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('WORKBENCH_EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('WORKBENCH_EMAIL_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('WORKBENCH_EMAIL_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('WORKBENCH_EMAIL_TLS', '1') == '1'
EMAIL_USE_SSL = os.environ.get('WORKBENCH_EMAIL_SSL', '0') == '1'
EMAIL_SUBJECT_PREFIX = ''
# 发件人默认跟随 SMTP 账号：多数邮箱服务（QQ / 163 / Gmail）要求 From 与登录账号一致，
# 否则会被拒绝或直接进垃圾邮件。想用别的发件人再显式设置 WORKBENCH_EMAIL_FROM。
DEFAULT_FROM_EMAIL = (os.environ.get('WORKBENCH_EMAIL_FROM')
                      or os.environ.get('WORKBENCH_EMAIL_USER')
                      or 'no-reply@localhost')
# 邮件：用于成员自助找回密码。
# 只有「开发模式 且 没配 SMTP」时才用控制台后端（重置链接/验证码直接打印在 runserver 输出里，
# 便于本地调试）。一旦配了 WORKBENCH_EMAIL_HOST 就真实发信 —— 这样本地也能收到真邮件，
# 否则开发时会被强制吞掉，出现「提示已发送但收不到」的假象。
if DEBUG and not EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# 重置链接有效期：默认 1 小时。Django 默认是 3 天，对一个 10 人团队来说太长。
PASSWORD_RESET_TIMEOUT = int(os.environ.get('WORKBENCH_RESET_TIMEOUT', 60 * 60))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.environ.get('WORKBENCH_HTTPS') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
if os.environ.get('WORKBENCH_TRUST_PROXY') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = int(os.environ.get('WORKBENCH_HSTS_SECONDS', '31536000')) if SESSION_COOKIE_SECURE else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('WORKBENCH_HSTS_SUBDOMAINS') == '1'
SECURE_HSTS_PRELOAD = os.environ.get('WORKBENCH_HSTS_PRELOAD') == '1'
ADMINS = [('Operations', email.strip()) for email in os.environ.get('WORKBENCH_ADMINS', '').split(',') if email.strip()]
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'formatters': {'standard': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'}},
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
        'mail_admins': {'class': 'core.logging.OperationsEmailHandler', 'level': 'ERROR'},
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'django.request': {'handlers': ['console', 'mail_admins'], 'level': 'ERROR', 'propagate': False}},
}
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# Enable direct download links only after the corresponding GitHub Release is public.
WORKBENCH_DESKTOP_RELEASE = os.environ.get('WORKBENCH_DESKTOP_RELEASE', '')

WORKBENCH_SEARCH_URL = os.environ.get('WORKBENCH_SEARCH_URL', '')
WORKBENCH_SEARCH_BACKEND = os.environ.get('WORKBENCH_SEARCH_BACKEND', 'auto')
WORKBENCH_WEB_RENDER = os.environ.get('WORKBENCH_WEB_RENDER', '1') == '1'
WORKBENCH_PROXY_DNS_FALLBACK = os.environ.get('WORKBENCH_PROXY_DNS_FALLBACK', '1') == '1'
