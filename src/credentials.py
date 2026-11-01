"""Private CA with separate source/host identities; no machine trust-store changes."""

from __future__ import annotations

import datetime as dt
import os
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SERVER_NAME = "triplesense"


def generate_pair(destination: Path) -> None:
    """Create credentials once. Never overwrite an existing identity."""
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DualSense Bridge Pair")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, None, None),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    for role, purpose in (
        ("source", ExtendedKeyUsageOID.SERVER_AUTH),
        ("host", ExtendedKeyUsageOID.CLIENT_AUTH),
    ):
        folder = destination / role
        folder.mkdir(mode=0o700)
        key = ec.generate_private_key(ec.SECP256R1())
        name = SERVER_NAME if role == "source" else "triplesense-host"
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(True, False, False, False, False, False, False, None, None),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([purpose]), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        private = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        for filename, data in (
            ("key.pem", private),
            ("cert.pem", cert.public_bytes(serialization.Encoding.PEM)),
            ("ca.pem", ca.public_bytes(serialization.Encoding.PEM)),
        ):
            # Restrictive POSIX mode; on Windows the containing user's ACL applies.
            fd = os.open(folder / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
    # The CA private key exists only in memory and is never stored or shared.


def tls_context(folder: Path, *, server: bool) -> ssl.SSLContext:
    purpose = ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH
    context = ssl.create_default_context(purpose, cafile=str(folder / "ca.pem"))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(str(folder / "cert.pem"), str(folder / "key.pem"))
    return context
