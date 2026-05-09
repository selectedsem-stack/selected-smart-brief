import os
from dotenv import load_dotenv

load_dotenv()


def load_config() -> dict:
    return {
        "SECRET_KEY": os.getenv("SECRET_KEY", "dev-fallback-not-secure"),
        "BASE_URL": os.getenv("BASE_URL", "http://localhost:5000"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "DEFAULT_TEMPLATE": os.getenv("DEFAULT_TEMPLATE", "seo-ppc-brief"),
        "DB_PATH": os.getenv("DB_PATH", "data/briefs.db"),
        "MANAGER_EMAIL": os.getenv("MANAGER_EMAIL", ""),
        "AI_AVAILABLE": bool(os.getenv("ANTHROPIC_API_KEY")),
        "ACCESS_USER": os.getenv("ACCESS_USER", "selected"),
        "ACCESS_PASSWORD": os.getenv("ACCESS_PASSWORD", ""),
        "RESEND_API_KEY": os.getenv("RESEND_API_KEY", ""),
        "RESEND_FROM_EMAIL": os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev"),
    }
