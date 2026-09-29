"""Erzeugt ein VAPID-Schlüsselpaar für Web Push.

Aufruf (im backend/-Verzeichnis):  python -m scripts.generate_vapid_keys
Ausgabe in .env.prod übernehmen. Der Private Key ist geheim, der Public Key nicht.
Achtung: Neue Keys machen alle bestehenden Subscriptions ungültig.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    vapid = Vapid()
    vapid.generate_keys()
    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print(f"VAPID_PUBLIC_KEY={_b64url(public_raw)}")
    print(f"VAPID_PRIVATE_KEY={_b64url(private_raw)}")


if __name__ == "__main__":
    main()
