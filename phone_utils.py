"""phone_utils.py — small helpers for safely formatting phone numbers in logs."""


def mask_phone(phone: str) -> str:
    """Return phone number with only last 4 digits visible for safe logging."""
    if not phone or len(phone) < 4:
        return "****"
    return f"****{phone[-4:]}"
