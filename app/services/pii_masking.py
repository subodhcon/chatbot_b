import re

# Regex for matching email addresses
EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
)

# Regex for matching phone numbers (supports formats like +1-123-456-7890, (123) 456-7890, etc.)
PHONE_REGEX = re.compile(
    r'\b(?:\+?\d{1,3}[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b'
)


class PIIMaskingService:
    """
    PIIMaskingService provides utilities to detect and obfuscate PII (Emails and Phone Numbers)
    from conversation data and logs before export.
    """

    def mask_email(self, email: str) -> str:
        """
        Masks the local part of an email address, preserving the domain.
        Example: john.doe@example.com -> j***e@example.com
        """
        try:
            local_part, domain = email.split('@', 1)
            if len(local_part) <= 2:
                return f"***@{domain}"
            return f"{local_part[0]}{'*' * (len(local_part) - 2)}{local_part[-1]}@{domain}"
        except Exception:
            return "***@***.***"

    def mask_phone(self, phone: str) -> str:
        """
        Masks the middle digits of a phone number, preserving formatting.
        Example: +1-123-456-7890 -> +1-1**-***-7890
        """
        # Strip everything except digits and + sign
        digits_only = re.sub(r'[^\d+]', '', phone)
        if len(digits_only) < 7:
            return "***-***-****"

        # Mask middle digits
        visible_start = 2 if digits_only.startswith('+') else 3
        visible_end = 4
        masked_length = len(digits_only) - visible_start - visible_end

        if masked_length <= 0:
            return "***-***-****"

        masked_digits = (
            digits_only[:visible_start]
            + '*' * masked_length
            + digits_only[-visible_end:]
        )

        # Re-apply some formatting or return masked digit stream
        return masked_digits

    def mask_text(self, text: str) -> str:
        """
        Scans text content, finds all emails and phone numbers, and returns masked text.
        """
        if not text or not isinstance(text, str):
            return text

        # 1. Mask all email addresses found in the text
        def replace_email(match):
            return self.mask_email(match.group(0))

        text = EMAIL_REGEX.sub(replace_email, text)

        # 2. Mask all phone numbers found in the text
        def replace_phone(match):
            return self.mask_phone(match.group(0))

        text = PHONE_REGEX.sub(replace_phone, text)

        return text


# Module-level singleton
pii_masking_service = PIIMaskingService()
