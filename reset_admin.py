#!/usr/bin/env python3
"""Ensure the admin user exists; optionally force-reset its password.

Runs on every container boot from docker-entrypoint-single.sh.

By default this is CREATE-ONLY: a missing admin user is created from
CRAWLDOCTOR_ADMIN_PASSWORD, but an existing one is left untouched so that
passwords changed via PUT /api/v1/auth/password survive restarts.

Set CRAWLDOCTOR_ADMIN_PASSWORD_RESET_ON_BOOT=true to force the password back to
CRAWLDOCTOR_ADMIN_PASSWORD on boot — useful to recover a locked-out admin.
Turn it off again afterwards, or in-app password changes will keep reverting.
"""

import sys

# Add the app directory to the path
sys.path.append('/app')

from app.database import SessionLocal
from app.services.auth import AuthService
from app.models.user import User
from app.config import settings


def ensure_admin_user():
    """Create the admin user if missing; reset its password only when asked."""
    auth_service = AuthService()
    db = SessionLocal()

    try:
        admin_user = db.query(User).filter(User.username == settings.admin_username).first()

        if not admin_user:
            admin_user = User(
                username=settings.admin_username,
                email=settings.admin_email,
                hashed_password=auth_service.hash_password(settings.admin_password),
                full_name="Administrator",
                is_active=True,
                is_superuser=True,
            )
            db.add(admin_user)
            db.commit()
            print(f"✅ Created admin user '{settings.admin_username}' from CRAWLDOCTOR_ADMIN_PASSWORD")
            return

        if not settings.admin_password_reset_on_boot:
            print(
                f"👤 Admin user '{settings.admin_username}' already exists — leaving password unchanged. "
                "Set CRAWLDOCTOR_ADMIN_PASSWORD_RESET_ON_BOOT=true to force a reset."
            )
            return

        admin_user.hashed_password = auth_service.hash_password(settings.admin_password)
        admin_user.is_active = True
        db.commit()
        print(
            f"🔄 Force-reset password for admin user '{settings.admin_username}' "
            "(CRAWLDOCTOR_ADMIN_PASSWORD_RESET_ON_BOOT is on — turn it off to keep in-app changes)"
        )

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    ensure_admin_user()
